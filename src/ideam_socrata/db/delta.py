"""Delta incremental diario: nuevas filas desde el high-water mark de cada dataset.

Para cada dataset estandar ya backfilleado:
  1. hwm = max(fechaobservacion) en observaciones.
  2. Pide a Socrata fechaobservacion > hwm (paginado SODA; el delta es pequeno).
  3. normalize_chunk (mismo floating_id que el backfill) -> COPY -> upsert DO UPDATE
     (IDEAM corrige valores retroactivamente).
Idempotente: re-ejecutar no duplica ni pierde filas.

Uso:
    python -m ideam_socrata.db.delta            # todos los datasets
    python -m ideam_socrata.db.delta --dataset s54a-sgyg
"""

import argparse
import logging
import time

from ..extract import iter_socrata_pages
from ..query_validation import quote_soql
from ..transform import deduplicate_observations, normalize_chunk
from . import state
from .backfill import DATASETS_ESTANDAR, DICT_REEMPLAZO, _retry
from .connection import get_conn
from .copy_loader import load_dataframe

logger = logging.getLogger(__name__)


def delta_dataset(conn, dataset):
    dataset_id, col_fecha = dataset["id"], dataset["fecha_col"]
    hwm = state.get_hwm(conn, dataset_id)
    if hwm is None:
        logger.info("%s sin backfill todavia; delta omitido.", dataset_id)
        return 0

    where = f"{col_fecha} > {quote_soql(hwm.strftime('%Y-%m-%dT%H:%M:%S'))}"
    rows_loaded = 0
    for page in iter_socrata_pages(dataset_id, _retry, where_str=where, order=col_fecha):
        df = normalize_chunk(page, dataset_id, col_fecha, DICT_REEMPLAZO)
        df, _dups = deduplicate_observations(df, col_fecha)
        rows_loaded += load_dataframe(conn, df, mode="upsert")

    new_hwm = state.get_hwm(conn, dataset_id)
    state.mark(conn, dataset_id, "delta", "hwm", "done", rows_loaded=rows_loaded, hwm=new_hwm)
    logger.info("Delta %s: %s filas (hwm %s -> %s)", dataset_id, rows_loaded, hwm, new_hwm)
    print(f"  {dataset_id}: {rows_loaded:,} filas nuevas", flush=True)
    return rows_loaded


def main():
    parser = argparse.ArgumentParser(description="Delta incremental IDEAM -> Postgres")
    parser.add_argument("--dataset", default="all", help="id Socrata o 'all'")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True
    )

    objetivos = (
        DATASETS_ESTANDAR
        if args.dataset == "all"
        else [d for d in DATASETS_ESTANDAR if d["id"] == args.dataset]
    )
    if not objetivos:
        raise SystemExit(f"Dataset {args.dataset} no reconocido.")

    t0 = time.time()
    total = 0
    with get_conn() as conn:
        for dataset in objetivos:
            try:
                total += delta_dataset(conn, dataset)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                state.mark(conn, dataset["id"], "delta", "hwm", "error", error=str(exc)[:500])
                logger.error("Delta de %s fallo: %s", dataset["id"], exc)
        # Refrescar el resumen de catálogo que usa la API (si ya existe).
        try:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_catalogo")
            conn.commit()
            print("mv_catalogo refrescada", flush=True)
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.warning("No se pudo refrescar mv_catalogo: %s", exc)
    print(f"TOTAL delta: {total:,} filas en {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()

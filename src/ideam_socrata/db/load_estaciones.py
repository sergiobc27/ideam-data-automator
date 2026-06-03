"""Carga/actualiza la dimension `estaciones` desde el Catalogo Nacional (hp9r-jxuu).

Uso:
    python -m ideam_socrata.db.load_estaciones
"""

import logging
import time

import pandas as pd

from ..config import CATALOG_DATASET_ID, CLIENT, LIMIT, MAPEO_DEPARTAMENTOS
from ..transform import normalize_label
from .connection import get_conn

logger = logging.getLogger(__name__)

_CANONICO_POR_VARIANTE = {
    normalize_label(variante): canonico
    for canonico, variantes in MAPEO_DEPARTAMENTOS.items()
    for variante in variantes
}

COLUMNS = [
    "codigoestacion", "nombre", "categoria", "tecnologia", "estado",
    "departamento", "departamento_norm", "municipio",
    "latitud", "longitud", "altitud",
    "fecha_instalacion", "fecha_suspension",
    "area_operativa", "area_hidrografica", "zona_hidrografica",
    "subzona_hidrografica", "corriente", "entidad",
]

UPSERT = f"""
INSERT INTO estaciones ({', '.join(COLUMNS)}, updated_at)
VALUES ({', '.join(['%s'] * len(COLUMNS))}, now())
ON CONFLICT (codigoestacion) DO UPDATE SET
  {', '.join(f'{c} = EXCLUDED.{c}' for c in COLUMNS[1:])},
  updated_at = now()
"""


def _retry(func, descripcion, max_intentos=5):
    for i in range(max_intentos):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error en %s (intento %s/%s): %s", descripcion, i + 1, max_intentos, exc)
            if i == max_intentos - 1:
                raise
            time.sleep(2 ** i)


def fetch_catalogo():
    rows, offset = [], 0
    while True:
        page = _retry(
            lambda: CLIENT.get(CATALOG_DATASET_ID, limit=LIMIT, offset=offset, order=":id"),
            f"catalogo offset={offset}",
        )
        if not page:
            break
        rows.extend(page)
        if len(page) < LIMIT:
            break
        offset += LIMIT
    return rows


def _fecha(value):
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def _num(value):
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def to_record(row):
    codigo = row.get("codigo")
    if codigo is None or str(codigo).strip() == "":
        return None
    departamento = row.get("departamento")
    departamento_norm = _CANONICO_POR_VARIANTE.get(
        normalize_label(departamento), normalize_label(departamento) or None
    )
    return (
        str(codigo).strip(),
        row.get("nombre"),
        row.get("categoria"),
        row.get("tecnologia"),
        row.get("estado"),
        departamento,
        departamento_norm,
        row.get("municipio"),
        _num(row.get("latitud")),
        _num(row.get("longitud")),
        _num(row.get("altitud")),
        _fecha(row.get("fecha_instalacion")),
        _fecha(row.get("fecha_suspension")),
        row.get("area_operativa"),
        row.get("area_hidrografica"),
        row.get("zona_hidrografica"),
        row.get("subzona_hidrografica"),
        row.get("corriente"),
        row.get("entidad"),
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rows = fetch_catalogo()
    records = [r for r in (to_record(row) for row in rows) if r is not None]
    print(f"Catalogo: {len(rows)} filas, {len(records)} validas", flush=True)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT, records)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM estaciones")
            total = cur.fetchone()[0]
    print(f"estaciones en DB: {total}", flush=True)


if __name__ == "__main__":
    main()

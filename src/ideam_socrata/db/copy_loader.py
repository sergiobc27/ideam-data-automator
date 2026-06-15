"""Carga masiva a Postgres: COPY a staging_obs + upsert idempotente.

El floating_id llega como hex (lo produce ideam_socrata.transform.add_floating_id,
unico punto de verdad) y aqui se convierte a BYTEA con decode(...,'hex').
"""

import logging

import pandas as pd
from psycopg.types.json import Jsonb

from .. import physical_ranges

logger = logging.getLogger(__name__)

# Cache de altitudes por estación (código sin ceros a la izquierda) para el saneo
# de presión. Se llena una vez por proceso desde `estaciones`; la dimensión casi
# no cambia y la ingesta es de vida corta.
_ALTITUDES = None

STAGING_COLUMNS = [
    "floating_id_hex",
    "source_dataset_id",
    "codigoestacion",
    "codigosensor",
    "fechaobservacion",
    "valorobservado",
    "nombreestacion",
    "departamento",
    "municipio",
    "zonahidrografica",
    "latitud",
    "longitud",
    "descripcionsensor",
    "unidadmedida",
]

_SELECT_FROM_STAGING = """
SELECT DISTINCT ON (floating_id_hex)
       decode(floating_id_hex, 'hex'),
       source_dataset_id, codigoestacion, codigosensor, fechaobservacion,
       valorobservado, nombreestacion, departamento, municipio, zonahidrografica,
       latitud, longitud, descripcionsensor, unidadmedida
FROM staging_obs_tmp
WHERE floating_id_hex IS NOT NULL
  AND fechaobservacion IS NOT NULL
  AND codigoestacion IS NOT NULL
"""

_INSERT_COLUMNS = """
(floating_id, source_dataset_id, codigoestacion, codigosensor, fechaobservacion,
 valorobservado, nombreestacion, departamento, municipio, zonahidrografica,
 latitud, longitud, descripcionsensor, unidadmedida)
"""

UPSERT_INSERT = (
    f"INSERT INTO observaciones {_INSERT_COLUMNS} {_SELECT_FROM_STAGING} "
    "ON CONFLICT (floating_id, fechaobservacion) DO NOTHING"
)

UPSERT_UPDATE = (
    f"INSERT INTO observaciones {_INSERT_COLUMNS} {_SELECT_FROM_STAGING} "
    "ON CONFLICT (floating_id, fechaobservacion) DO UPDATE SET "
    "valorobservado = EXCLUDED.valorobservado, "
    "nombreestacion = EXCLUDED.nombreestacion, "
    "departamento = EXCLUDED.departamento, "
    "municipio = EXCLUDED.municipio, "
    "zonahidrografica = EXCLUDED.zonahidrografica, "
    "latitud = EXCLUDED.latitud, "
    "longitud = EXCLUDED.longitud, "
    "descripcionsensor = EXCLUDED.descripcionsensor, "
    "unidadmedida = EXCLUDED.unidadmedida, "
    "ingested_at = now()"
)


def _staging_frame(df):
    """Reordena el dataframe normalizado al layout de staging_obs."""
    frame = df.rename(columns={"floating_id": "floating_id_hex"})
    frame = frame.reindex(columns=STAGING_COLUMNS)
    return frame.astype(object).where(pd.notna(frame), None)


def _altitudes(conn):
    """Mapa código-normalizado -> altitud (m) desde `estaciones`, cacheado."""
    global _ALTITUDES
    if _ALTITUDES is None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ltrim(codigoestacion, '0'), altitud FROM estaciones WHERE altitud IS NOT NULL"
                )
                _ALTITUDES = {code: float(alt) for code, alt in cur.fetchall()}
        except Exception:
            logger.exception("No se pudo cargar altitudes; el saneo de presión usará el rango de respaldo")
            _ALTITUDES = {}
    return _ALTITUDES


def _record_rejections(cur, rejected):
    """Aparta a observaciones_rechazos las filas físicamente imposibles (con su
    motivo y la fila cruda en JSONB). No destructivo: el dato no se pierde."""
    rows = []
    for rec in rejected.to_dict("records"):
        motivo = rec.pop("motivo", None)
        dataset_id = rec.get("source_dataset_id")
        raw = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in rec.items()}
        rows.append((dataset_id, Jsonb(raw), motivo))
    cur.executemany(
        "INSERT INTO observaciones_rechazos (source_dataset_id, raw, motivo) VALUES (%s, %s, %s)",
        rows,
    )


def _sanitize(conn, frame):
    """Parte el frame de staging en (aceptado, rechazado) por rango físico.
    Defensivo: ante cualquier fallo, devuelve el frame sin filtrar (no se pierde
    dato ni se rompe la ingesta)."""
    if frame.empty:
        return frame, frame.iloc[0:0]
    try:
        dataset_id = next((d for d in frame["source_dataset_id"] if d is not None), None)
        if dataset_id is None:
            return frame, frame.iloc[0:0]
        return physical_ranges.split_frame(frame, dataset_id, _altitudes(conn))
    except Exception:
        logger.exception("Saneo físico falló; se ingiere el lote sin filtrar")
        return frame, frame.iloc[0:0]


def load_dataframe(conn, df, mode="insert"):
    """COPY del dataframe normalizado a staging temporal y upsert a observaciones.

    El staging es una TEMP TABLE por conexión: cada hilo/worker del backfill
    paralelo tiene la suya, sin contención entre sí.
    mode='insert' (backfill, DO NOTHING) | mode='upsert' (delta, DO UPDATE).
    Devuelve filas efectivamente insertadas/actualizadas en observaciones.
    """
    if df is None or df.empty:
        return 0

    frame = _staging_frame(df)
    # Saneo físico (auditoría 2026-06-15): aparta lecturas imposibles a
    # observaciones_rechazos antes del upsert. Mismo conn/transacción = atómico.
    frame, rejected = _sanitize(conn, frame)
    sql = UPSERT_UPDATE if mode == "upsert" else UPSERT_INSERT

    affected = 0
    with conn.cursor() as cur:
        if not rejected.empty:
            _record_rejections(cur, rejected)
        if not frame.empty:
            cur.execute(
                "CREATE TEMP TABLE IF NOT EXISTS staging_obs_tmp (LIKE staging_obs)"
            )
            cur.execute("TRUNCATE staging_obs_tmp")
            with cur.copy(
                f"COPY staging_obs_tmp ({', '.join(STAGING_COLUMNS)}) FROM STDIN"
            ) as copy:
                for row in frame.itertuples(index=False, name=None):
                    copy.write_row(row)
            cur.execute(sql)
            affected = cur.rowcount
    conn.commit()

    if not rejected.empty:
        logger.info("Saneo: %s fila(s) apartada(s) a observaciones_rechazos", len(rejected))
    logger.debug("Lote cargado: staged=%s afectadas=%s mode=%s", len(frame), affected, mode)
    return affected

"""Carga masiva a Postgres: COPY a staging_obs + upsert idempotente.

El floating_id llega como hex (lo produce ideam_socrata.transform.add_floating_id,
unico punto de verdad) y aqui se convierte a BYTEA con decode(...,'hex').
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

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
    sql = UPSERT_UPDATE if mode == "upsert" else UPSERT_INSERT

    with conn.cursor() as cur:
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

    logger.debug("Lote cargado: staged=%s afectadas=%s mode=%s", len(frame), affected, mode)
    return affected

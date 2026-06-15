"""Carga masiva a Postgres: COPY a staging_obs + upsert idempotente.

El floating_id llega como hex (lo produce ideam_socrata.transform.add_floating_id,
unico punto de verdad) y aqui se convierte a BYTEA con decode(...,'hex').
"""

import logging
import math

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

# Columnas obligatorias (NOT NULL en el esquema y/o clave del floating_id): sin
# ellas la fila no puede materializarse en observaciones, así que se rechaza.
_REQUIRED_COLUMNS = ("floating_id_hex", "codigoestacion", "fechaobservacion")
# Columnas numéricas: un no-finito (inf/-inf/nan) rompe el COPY -> se anula (NULL).
_NUMERIC_COLUMNS = ("valorobservado", "latitud", "longitud")
# Techo defensivo de longitud de texto: trunca strings absurdos antes de que
# Postgres aborte el COPY (los campos de texto del esquema no llevan límite, pero
# un valor multi-KB casi siempre es corrupción de la fuente).
_MAX_TEXT_LEN = 2000

_COL_INDEX = {col: i for i, col in enumerate(STAGING_COLUMNS)}


def _coerce_row_for_copy(row):
    """Coacciona UNA fila (tupla en orden STAGING_COLUMNS) a valores COPY-safe.

    Devuelve (fila_segura, None) si la fila es cargable —anulando celdas no
    finitas y truncando textos gigantes— o (None, motivo) si le falta un campo
    obligatorio (fecha/código/floating_id) y debe desviarse a rechazos. Pura y
    testeable: NO toca la DB. Evita que una sola fila mala aborte todo el lote.
    """
    cells = list(row)

    for col in _REQUIRED_COLUMNS:
        valor = cells[_COL_INDEX[col]]
        if valor is None or (isinstance(valor, float) and math.isnan(valor)) or valor is pd.NaT:
            return None, f"{col} ausente/NaT (fila no cargable)"

    for col in _NUMERIC_COLUMNS:
        idx = _COL_INDEX[col]
        valor = cells[idx]
        if isinstance(valor, float) and not math.isfinite(valor):
            cells[idx] = None  # inf/-inf/nan -> NULL: la fila sobrevive

    for col, idx in _COL_INDEX.items():
        if col in _NUMERIC_COLUMNS:
            continue
        valor = cells[idx]
        if isinstance(valor, str) and len(valor) > _MAX_TEXT_LEN:
            cells[idx] = valor[:_MAX_TEXT_LEN]

    return tuple(cells), None


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
    """Mapa código-normalizado -> altitud (m) desde `estaciones`, cacheado.

    Aislamiento transaccional (fix crítico): el SELECT comparte la conexión con
    el COPY que viene después. Si falla, se hace `conn.rollback()` ANTES de
    devolver para no dejar la transacción en estado abortado (que tumbaría el
    COPY y todos los lotes siguientes). Un fallo NO se cachea como `{}`: se
    devuelve un respaldo vacío para ESTE lote pero se permite reintentar en el
    siguiente (la DB pudo recuperarse).
    """
    global _ALTITUDES
    if _ALTITUDES is not None:
        return _ALTITUDES
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ltrim(codigoestacion, '0'), altitud FROM estaciones WHERE altitud IS NOT NULL"
            )
            _ALTITUDES = {code: float(alt) for code, alt in cur.fetchall()}
        return _ALTITUDES
    except Exception:
        logger.exception("No se pudo cargar altitudes; el saneo de presión usará el rango de respaldo")
        try:
            conn.rollback()  # deshace la transacción abortada; no envenena el COPY
        except Exception:
            logger.exception("rollback tras fallo de altitudes también falló")
        return {}  # respaldo SOLO para este lote; sin cachear -> reintento posible


def _coerce_frame_rows(frame):
    """Recorre el frame ya saneado y devuelve (filas_safe, no_cargables).

    `filas_safe`: lista de tuplas COPY-safe (orden STAGING_COLUMNS) listas para
    `copy.write_row`. `no_cargables`: lista de (fila_original, motivo) a desviar a
    observaciones_rechazos. Pura (no toca DB) y testeable.
    """
    safe_rows = []
    no_cargables = []
    if frame.empty:
        return safe_rows, no_cargables
    for row in frame.itertuples(index=False, name=None):
        safe, motivo = _coerce_row_for_copy(row)
        if safe is None:
            no_cargables.append((row, motivo))
        else:
            safe_rows.append(safe)
    return safe_rows, no_cargables


def _raw_from_row(row):
    """JSONB-safe dict de una fila (tupla en orden STAGING_COLUMNS), para rechazos."""
    raw = {}
    for col, valor in zip(STAGING_COLUMNS, row):
        if valor is pd.NaT or (isinstance(valor, float) and math.isnan(valor)):
            raw[col] = None
        elif hasattr(valor, "isoformat"):
            raw[col] = valor.isoformat()
        else:
            raw[col] = valor
    return raw


def _record_rejection_rows(cur, no_cargables):
    """Aparta a observaciones_rechazos filas COPY-no-cargables (fecha/código
    ausentes). Mismo destino que el saneo físico: el dato no se pierde."""
    rows = []
    for row, motivo in no_cargables:
        raw = _raw_from_row(row)
        rows.append((raw.get("source_dataset_id"), Jsonb(raw), motivo))
    cur.executemany(
        "INSERT INTO observaciones_rechazos (source_dataset_id, raw, motivo) VALUES (%s, %s, %s)",
        rows,
    )


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
    # Coacción COPY-safe (fix crítico): las filas aceptadas por el saneo aún
    # pueden traer celdas que abortarían el COPY (fecha NaT, valor no finito,
    # texto gigante). Se anulan/truncan las recuperables y se DESVÍAN las no
    # cargables a `no_cargables`, de modo que una sola fila mala nunca tumba el
    # lote entero (ni el rollback que perdería los rechazos ya insertados).
    safe_rows, no_cargables = _coerce_frame_rows(frame)
    sql = UPSERT_UPDATE if mode == "upsert" else UPSERT_INSERT

    affected = 0
    with conn.cursor() as cur:
        if not rejected.empty:
            _record_rejections(cur, rejected)
        if no_cargables:
            _record_rejection_rows(cur, no_cargables)
        if safe_rows:
            cur.execute(
                "CREATE TEMP TABLE IF NOT EXISTS staging_obs_tmp (LIKE staging_obs)"
            )
            cur.execute("TRUNCATE staging_obs_tmp")
            with cur.copy(
                f"COPY staging_obs_tmp ({', '.join(STAGING_COLUMNS)}) FROM STDIN"
            ) as copy:
                for row in safe_rows:
                    copy.write_row(row)
            cur.execute(sql)
            affected = cur.rowcount
    conn.commit()

    apartadas = len(rejected) + len(no_cargables)
    if apartadas:
        logger.info("Saneo: %s fila(s) apartada(s) a observaciones_rechazos", apartadas)
    logger.debug("Lote cargado: staged=%s afectadas=%s mode=%s", len(safe_rows), affected, mode)
    return affected

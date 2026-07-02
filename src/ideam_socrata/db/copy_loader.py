"""Carga masiva a Postgres: COPY a staging_obs + upsert idempotente.

El floating_id llega como hex (lo produce ideam_socrata.transform.add_floating_id,
unico punto de verdad) y aqui se convierte a BYTEA con decode(...,'hex').

ESPEJO PURO (2026-06-17): `observaciones` es una copia EXACTA de Socrata. La
ingesta NO filtra por rango fisico (decision del proyecto: poder compartir el
espejo tal cual, sin modificacion). La unica desviacion es ESTRUCTURAL: filas sin
floating_id/codigo/fecha violan NOT NULL y no son observaciones validas, asi que
van a observaciones_rechazos (sin ellas la fila no puede materializarse). La QC
fisica de lecturas imposibles vive ahora en la CAPA DE CALCULO (vistas/agregados +
topes de la API), no en la ingesta.

FUENTE UNICA de los rangos/topes fisicos: ideam_socrata.physical_ranges. Alli
viven tanto los rangos por-lectura (reject_reason/split_frame, para tests y usos
futuros de saneo) como los techos de cordura de la capa de calculo
(MAX_PRECIP_DIARIA_MM / MAX_PRECIP_MENSUAL_MM), que la API importa en vez de
repetir numeros magicos (auditoria datos-correctitud #5). El precomputo IDF
(deploy/idf_schema.sql) usa umbrales mas estrictos a proposito (dato de 10 min y
ventana movil) que, por ser SQL, no pueden importar esas constantes; su
equivalencia queda documentada en ese archivo. Recordatorio: nada de esto filtra
en la INGESTA: este loader escribe el espejo tal cual.
"""

import logging
import math

import pandas as pd
from psycopg.types.json import Jsonb

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

    OJO: esto NO es saneo físico. Un valor numérico fuera de rango (precip
    imposible, etc.) NO se filtra aquí: entra al espejo tal cual (espejo puro).
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


def _coerce_frame_rows(frame):
    """Recorre el frame de staging y devuelve (filas_safe, no_cargables).

    `filas_safe`: lista de tuplas COPY-safe (orden STAGING_COLUMNS) listas para
    `copy.write_row`. `no_cargables`: lista de (fila_original, motivo) a desviar a
    observaciones_rechazos (solo filas sin fecha/código/floating_id). Pura (no
    toca DB) y testeable.
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
    """Aparta a observaciones_rechazos filas ESTRUCTURALMENTE no cargables
    (fecha/código/floating_id ausentes). No es saneo físico: solo filas que
    violarían NOT NULL. El dato no se pierde (queda en rechazos)."""
    rows = []
    for row, motivo in no_cargables:
        raw = _raw_from_row(row)
        rows.append((raw.get("source_dataset_id"), Jsonb(raw), motivo))
    cur.executemany(
        "INSERT INTO observaciones_rechazos (source_dataset_id, raw, motivo) VALUES (%s, %s, %s)",
        rows,
    )


def load_dataframe(conn, df, mode="insert"):
    """COPY del dataframe normalizado a staging temporal y upsert a observaciones.

    El staging es una TEMP TABLE por conexión: cada hilo/worker del backfill
    paralelo tiene la suya, sin contención entre sí.
    mode='insert' (backfill, DO NOTHING) | mode='upsert' (delta, DO UPDATE).
    Devuelve filas efectivamente insertadas/actualizadas en observaciones.

    ESPEJO PURO: NO hay saneo físico. Toda fila estructuralmente válida entra a
    observaciones tal cual viene de Socrata. Solo se desvían a rechazos las filas
    sin fecha/código/floating_id (no cargables), para que una fila mala no aborte
    el lote.
    """
    if df is None or df.empty:
        return 0

    frame = _staging_frame(df)
    # Solo coacción COPY-safe + desvío estructural. SIN filtro de rango físico.
    safe_rows, no_cargables = _coerce_frame_rows(frame)
    sql = UPSERT_UPDATE if mode == "upsert" else UPSERT_INSERT

    affected = 0
    with conn.cursor() as cur:
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

    if no_cargables:
        logger.info(
            "Ingesta: %s fila(s) no cargable(s) (sin fecha/código) a observaciones_rechazos",
            len(no_cargables),
        )
    logger.debug("Lote cargado: staged=%s afectadas=%s mode=%s", len(safe_rows), affected, mode)
    return affected

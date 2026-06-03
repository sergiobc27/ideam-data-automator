"""Estado de ingesta: backfill reanudable y high-water mark del delta."""

_UPSERT_STATE = """
INSERT INTO ingest_state (source_dataset_id, grain, chunk_key, status, rows_loaded, hwm_fecha, error, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, now())
ON CONFLICT (source_dataset_id, grain, chunk_key) DO UPDATE
SET status = EXCLUDED.status,
    rows_loaded = EXCLUDED.rows_loaded,
    hwm_fecha = EXCLUDED.hwm_fecha,
    error = EXCLUDED.error,
    updated_at = now()
"""


def mark(conn, dataset_id, grain, chunk_key, status, rows_loaded=0, hwm=None, error=None):
    with conn.cursor() as cur:
        cur.execute(_UPSERT_STATE, (dataset_id, grain, chunk_key, status, rows_loaded, hwm, error))
    conn.commit()


def done_chunks(conn, dataset_id, grain="backfill"):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_key FROM ingest_state WHERE source_dataset_id=%s AND grain=%s AND status='done'",
            (dataset_id, grain),
        )
        return {row[0] for row in cur.fetchall()}


def get_hwm(conn, dataset_id):
    """Max fechaobservacion ya cargada para un dataset (None si vacio)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(fechaobservacion) FROM observaciones WHERE source_dataset_id=%s",
            (dataset_id,),
        )
        return cur.fetchone()[0]

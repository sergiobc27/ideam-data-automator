import os

import psycopg


def get_dsn():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL no esta definido. En el servidor se carga desde /etc/ideam/ideam.env."
        )
    return dsn


def get_conn(autocommit=False):
    """Single connection for ingestion jobs (the API uses its own pool)."""
    return psycopg.connect(get_dsn(), autocommit=autocommit)

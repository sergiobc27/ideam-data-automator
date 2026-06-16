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
    """Single connection for ingestion jobs (the API uses its own pool).

    timezone=UTC EXPLICITO: los caggs y analytics asumen cubetas a medianoche
    UTC (time_bucket sobre timestamptz). Los timestamps de la ingesta llegan
    naive; sin fijar el timezone de sesion, Postgres los interpreta en el
    default del servidor. Si ese default no fuera UTC, las series quedarian
    desplazadas y romperian el read-side en silencio. Lo fijamos aqui como
    unica fuente de verdad explicita, simetrico al pool de la API (app/db.py)."""
    return psycopg.connect(get_dsn(), autocommit=autocommit, options="-c timezone=UTC")

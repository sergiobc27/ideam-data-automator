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

    timezone=America/Bogota EXPLICITO. Verificado en el box: el servidor PG corre
    con default America/Bogota y TODO el historico se ingirio con esa sesion; el
    pool de la API (app/db.py) y el exporter (to_char) tambien asumen
    America/Bogota, de modo que las marcas de tiempo naive del IDEAM (hora local)
    hacen round-trip correcto. Lo fijamos EXPLICITO para blindar la ingesta
    contra un cambio del default del servidor SIN alterar el comportamiento.
    OJO: NO poner UTC aqui -> desplazaria 5h los datos NUEVOS respecto al
    historico y al exporter (las cubetas diarias de obs_diario son a medianoche
    UTC por time_bucket sobre timestamptz, y el read-side ya lo maneja)."""
    return psycopg.connect(get_dsn(), autocommit=autocommit, options="-c timezone=America/Bogota")

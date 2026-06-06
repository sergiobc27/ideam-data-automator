"""Pool de conexiones, esquema propio de la API y rate limiting en Postgres."""

from pathlib import Path

from psycopg_pool import ConnectionPool

from .settings import settings

# statement_timeout: ninguna consulta de la API puede correr mas de 30s.
# Sin esto, un resumen pesado sobre la hypertable de 764M filas se quedaba
# minutos bloqueando workers de uvicorn (visto en produccion el 2026-06-06).
pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=8,
    open=False,
    kwargs={"options": "-c statement_timeout=30000"},
)

_SCHEMA_API = Path(__file__).with_name("schema_api.sql").read_text(encoding="utf-8")


def init_db():
    pool.open()
    with pool.connection() as conn:
        conn.execute(_SCHEMA_API)


_RATE_SQL = """
INSERT INTO api_rate_limit (scope, ip, window_start, hits)
VALUES (%(scope)s, %(ip)s, now(), 1)
ON CONFLICT (scope, ip) DO UPDATE SET
  hits = CASE WHEN api_rate_limit.window_start < now() - %(window)s::interval
              THEN 1 ELSE api_rate_limit.hits + 1 END,
  window_start = CASE WHEN api_rate_limit.window_start < now() - %(window)s::interval
                      THEN now() ELSE api_rate_limit.window_start END
RETURNING hits, window_start
"""


def check_rate_limit(scope, ip, limit, window_seconds=3600):
    """Limitador basado en Postgres (DEPRECADO).

    Los routers ahora usan ``app.ratelimit.check_rate_limit`` (en memoria, sin
    golpear la DB). Se conserva aquí por compatibilidad/datos históricos en la
    tabla api_rate_limit, pero no se usa en el flujo de requests.

    Devuelve (permitido, restantes, retry_after_seconds).
    """
    with pool.connection() as conn:
        row = conn.execute(
            _RATE_SQL, {"scope": scope, "ip": ip, "window": f"{window_seconds} seconds"}
        ).fetchone()
        hits, window_start = row
        if hits > limit:
            retry = conn.execute(
                "SELECT ceil(extract(epoch FROM (%s + %s::interval) - now()))::int",
                (window_start, f"{window_seconds} seconds"),
            ).fetchone()[0]
            return False, 0, max(retry, 1)
        return True, limit - hits, 0

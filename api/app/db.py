"""Pool de conexiones, esquema propio de la API y rate limiting en Postgres."""

from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

from .settings import settings

# statement_timeout: ninguna consulta de la API puede correr mas de 30s.
# Sin esto, un resumen pesado sobre la hypertable de 764M filas se quedaba
# minutos bloqueando workers de uvicorn (visto en produccion el 2026-06-06).
# timezone EXPLICITO (auditoria #4): los caggs estan alineados a UTC y el
# exporter formatea fechas con to_char asumiendo America/Bogota; fijarlo aqui
# evita que un default a UTC del servidor desplace las fechas 5h en silencio.
pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=8,
    open=False,
    kwargs={"options": "-c statement_timeout=30000 -c timezone=America/Bogota"},
)

_SCHEMA_API = Path(__file__).with_name("schema_api.sql").read_text(encoding="utf-8")


def init_db():
    pool.open()
    with pool.connection() as conn:
        try:
            # lock_timeout corto: si un lock (p. ej. un REFRESH MATERIALIZED VIEW
            # CONCURRENTLY de mv_catalogo en curso) impide reaplicar el esquema,
            # falla rápido en vez de esperar el statement_timeout de 30 s.
            conn.execute("SET lock_timeout = '5s'")
            conn.execute(_SCHEMA_API)
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as exc:
            # El esquema es idempotente y en producción los objetos YA existen; un
            # lock transitorio NO debe tumbar el arranque de la API. Se registra y
            # se continúa (un reinicio durante un refresh de mv_catalogo ya no cae).
            conn.rollback()
            print(f"[init_db] esquema no reaplicado por lock/timeout; continúo (objetos ya existen): {exc}")


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
    """Limitador basado en Postgres: atómico, compartido entre procesos y
    persistente entre reinicios. Lo usa el scope 'export' (baja frecuencia,
    tope que importa de verdad); las lecturas usan ``app.ratelimit`` en
    memoria para no golpear la DB en cada panel.

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

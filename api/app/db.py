"""Pool de conexiones, esquema propio de la API y rate limiting en Postgres."""

import random
import time
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from .settings import settings

# statement_timeout: ninguna consulta de la API puede correr mas de 30s.
# Sin esto, un resumen pesado sobre la hypertable de 764M filas se quedaba
# minutos bloqueando workers de uvicorn (visto en produccion el 2026-06-06).
# timezone EXPLICITO (auditoria #4): los caggs estan alineados a UTC y el
# exporter formatea fechas con to_char asumiendo America/Bogota; fijarlo aqui
# evita que un default a UTC del servidor desplace las fechas 5h en silencio.
_CONN_KWARGS = {"options": "-c statement_timeout=30000 -c timezone=America/Bogota"}

# check=check_connection (auditoria 2026-07-01): valida la conexion al
# entregarla; una muerta por un corte del tunel Cloudflare->box se descarta y
# se entrega otra, en vez de fallar la consulta con OperationalError.
pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=6,
    open=False,
    check=ConnectionPool.check_connection,
    kwargs=_CONN_KWARGS,
)

# Pool DEDICADO a las conexiones LARGAS del export (COPY/stream/count con
# statement_timeout de 900s), separado del pool web (auditoria 2026-07-01):
# asi los jobs largos no acaparan las conexiones que sirven lecturas y
# /api/ready. max_size=2 = max_workers del EXECUTOR del exporter (cada job
# retiene UNA conexion larga a la vez); las queries cortas del flujo de export
# (claim atomico, _update de progreso, catalogo, reconciler) siguen usando el
# pool web. Total por proceso: 6 + 2 = 8, igual que antes de separar.
export_pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=2,
    open=False,
    check=ConnectionPool.check_connection,
    kwargs=_CONN_KWARGS,
)

_SCHEMA_API = Path(__file__).with_name("schema_api.sql").read_text(encoding="utf-8")


def init_db():
    pool.open()
    export_pool.open()
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


# Reintento corto para LECTURAS idempotentes (auditoria 2026-07-01): el tunel
# Cloudflare->box tiene hipos transitorios (502/cortes) que matan conexiones a
# mitad de consulta; sin reintento, cada hipo se volvia un 500 visible en
# endpoints re-ejecutables sin efectos (meta, date-range, catalogo, preview).
# SOLO lecturas: las escrituras y el flujo de export (INSERT de export_jobs,
# claim atomico de _run_job) NO pasan por aqui, reintentarlas podria duplicar
# efectos.
_READ_ATTEMPTS = 3  # 1 intento + 2 reintentos
_READ_BACKOFF_S = 0.1  # base corta, crece linealmente y lleva jitter


def read_with_retry(operation):
    """Ejecuta ``operation()`` (una lectura idempotente que abre SU PROPIA
    conexion via ``pool.connection()``) reintentando ante errores de conexion
    (OperationalError/InterfaceError). Cada reintento toma una conexion fresca
    del pool; las muertas las descarta el ``check`` del pool. PoolTimeout
    (subclase de OperationalError) NO se reintenta: pool agotado no es un hipo
    del tunel y reintentar solo agrava la contencion."""
    for attempt in range(1, _READ_ATTEMPTS + 1):
        try:
            return operation()
        except PoolTimeout:
            raise
        except (psycopg.OperationalError, psycopg.InterfaceError):
            if attempt == _READ_ATTEMPTS:
                raise
            time.sleep(_READ_BACKOFF_S * attempt + random.uniform(0.0, 0.1))


# Poda de ventanas viejas: sin esto la tabla crece una fila por (scope, ip)
# para siempre (rotación de IPs = crecimiento sin tope, hallazgo de auditoría
# 2026-06-11, simétrico a la fuga del limitador en memoria). La tabla es
# diminuta y el scope 'export' es de baja frecuencia, así que un DELETE por
# chequeo es despreciable. OJO: usa la ventana del scope llamante; hoy solo
# 'export' (3600s) vive en PG — si otro scope con ventana mayor migra aquí,
# guardar la ventana por fila.
_PRUNE_SQL = """
DELETE FROM api_rate_limit WHERE window_start < now() - 2 * %(window)s::interval
"""

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
        conn.execute(_PRUNE_SQL, {"window": f"{window_seconds} seconds"})
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

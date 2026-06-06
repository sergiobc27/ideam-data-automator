"""Rate limiting liviano en memoria (sin dependencias externas).

Reemplaza al limitador basado en Postgres para los endpoints de lectura
(catálogo/preview/analytics) y la planificación de export. Mantiene un dict
por (scope, ip) con una ventana deslizante simple: si la ventana expiró se
reinicia el contador.

IMPORTANTE: el estado vive en el proceso. Con 2 workers de uvicorn el límite
es POR-WORKER (un cliente podría hacer hasta 2x el límite configurado). Es un
candado anti-abuso "barato", aceptable para este despliegue; si en el futuro se
necesita un límite global exacto, mover el contador a Redis o a Postgres.

No es seguro para escritura concurrente entre hilos a nivel de microsegundo,
pero el peor caso es contar de menos un par de hits bajo carrera: irrelevante
para el objetivo (frenar abuso, no contabilidad exacta).
"""

import threading
import time

# (scope, ip) -> (window_start_epoch, hits)
_BUCKETS: dict[tuple[str, str], tuple[float, int]] = {}
_LOCK = threading.Lock()


def check_rate_limit(scope, ip, limit, window_seconds=3600, now=None):
    """Registra un hit y decide si se permite.

    Devuelve (permitido: bool, restantes: int, retry_after_seconds: int).
    `now` es inyectable para tests (epoch en segundos).
    """
    current = time.time() if now is None else now
    key = (scope, ip)
    with _LOCK:
        window_start, hits = _BUCKETS.get(key, (current, 0))
        if current - window_start >= window_seconds:
            # La ventana expiró: reiniciar.
            window_start, hits = current, 0
        hits += 1
        _BUCKETS[key] = (window_start, hits)
        if hits > limit:
            retry = window_seconds - (current - window_start)
            return False, 0, max(int(retry), 1)
        return True, limit - hits, 0


def reset():
    """Limpia el estado (uso en tests)."""
    with _LOCK:
        _BUCKETS.clear()

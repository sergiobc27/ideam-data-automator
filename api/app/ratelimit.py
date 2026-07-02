"""Rate limiting liviano en memoria (sin dependencias externas).

Reemplaza al limitador basado en Postgres para los endpoints de lectura
(catálogo/preview/analytics) y la planificación de export. Mantiene un dict
por (scope, ip) con una ventana deslizante simple: si la ventana expiró se
reinicia el contador.

IMPORTANTE: el estado vive en el proceso. Con 2 workers de uvicorn el límite
es POR-WORKER (un cliente podría hacer hasta 2x el límite configurado). Por eso
el default de rate_limit_catalog_per_hour (settings.py) está calibrado a la
MITAD del presupuesto por IP deseado (auditoría 2026-07-01). Es un candado
anti-abuso "barato", aceptable para este despliegue; si en el futuro se
necesita un límite global exacto, mover el contador a Redis o a Postgres
(el scope 'export', el único con tope que importa de verdad, ya usa el
limitador atómico en Postgres: db.check_rate_limit).

No es seguro para escritura concurrente entre hilos a nivel de microsegundo,
pero el peor caso es contar de menos un par de hits bajo carrera: irrelevante
para el objetivo (frenar abuso, no contabilidad exacta).
"""

import threading
import time

# (scope, ip) -> (window_start_epoch, hits)
_BUCKETS: dict[tuple[str, str], tuple[float, int]] = {}
_LOCK = threading.Lock()

# Anti fuga de memoria: el dict crecería sin tope si un atacante rota IPs (cada
# IP nueva crea una entrada que sin poda jamás se libera). Podamos las entradas
# cuya ventana ya expiró cada _PRUNE_EVERY operaciones; y si aun así se supera
# _MAX_BUCKETS (ráfaga de IPs frescas, todavía no expiradas), vaciamos todo como
# último recurso. El peor caso es contar de menos algunos hits: aceptable para
# un candado anti-abuso (no es contabilidad exacta).
_PRUNE_EVERY = 512
_MAX_BUCKETS = 20000
_ops = 0


def _maybe_prune_locked(current, window_seconds):
    """Poda entradas expiradas (llamar con _LOCK tomado)."""
    global _ops
    _ops += 1
    if _ops % _PRUNE_EVERY != 0 and len(_BUCKETS) <= _MAX_BUCKETS:
        return
    expired = [k for k, (ws, _) in _BUCKETS.items() if current - ws >= window_seconds]
    for k in expired:
        del _BUCKETS[k]
    if len(_BUCKETS) > _MAX_BUCKETS:
        # Ráfaga de IPs frescas: tope duro de memoria.
        _BUCKETS.clear()


def check_rate_limit(scope, ip, limit, window_seconds=3600, now=None):
    """Registra un hit y decide si se permite.

    Devuelve (permitido: bool, restantes: int, retry_after_seconds: int).
    `now` es inyectable para tests (epoch en segundos).
    """
    current = time.time() if now is None else now
    key = (scope, ip)
    with _LOCK:
        _maybe_prune_locked(current, window_seconds)
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
    global _ops
    with _LOCK:
        _BUCKETS.clear()
        _ops = 0

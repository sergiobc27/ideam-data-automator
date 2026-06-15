"""Utilidades HTTP compartidas por los routers.

`client_ip` es la fuente ÚNICA de la IP del cliente: detrás del Worker de
Cloudflare la IP real llega en `cf-connecting-ip`; en local/desarrollo se cae al
host del cliente de ASGI. Antes estaba copiada idéntica en cuatro routers
(analytics, export, catalog_routes, preview) y podían divergir.
"""

from fastapi import Request


def client_ip(request: Request) -> str:
    """IP del cliente para el rate-limit: prioriza cf-connecting-ip (Cloudflare),
    cae al host del cliente y por último a '?' si no hay info."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")

"""`_client_ip` debe vivir en UN solo lugar (app.http_utils.client_ip) y los
cuatro routers que lo usaban (analytics, export, catalog_routes, preview) deben
referenciar esa misma función, no copias divergentes.
"""

from types import SimpleNamespace

from app import http_utils
from app.routers import analytics, catalog_routes, export, preview


def _fake_request(headers=None, host=None):
    client = SimpleNamespace(host=host) if host is not None else None
    return SimpleNamespace(headers=headers or {}, client=client)


def test_extrae_cf_connecting_ip_con_prioridad():
    req = _fake_request(headers={"cf-connecting-ip": "1.2.3.4"}, host="9.9.9.9")
    assert http_utils.client_ip(req) == "1.2.3.4"


def test_cae_al_host_del_cliente():
    req = _fake_request(headers={}, host="9.9.9.9")
    assert http_utils.client_ip(req) == "9.9.9.9"


def test_sin_cliente_devuelve_placeholder():
    req = _fake_request(headers={})
    assert http_utils.client_ip(req) == "?"


def test_los_cuatro_routers_usan_el_helper_compartido():
    # Misma función (no copias): garantiza que no vuelvan a divergir.
    assert analytics._client_ip is http_utils.client_ip
    assert export._client_ip is http_utils.client_ip
    assert catalog_routes._client_ip is http_utils.client_ip
    assert preview._client_ip is http_utils.client_ip

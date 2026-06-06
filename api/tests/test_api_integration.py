"""Tests de integración por la pila ASGI real (TestClient) SIN Postgres.

Estrategia:
- No se usa TestClient como context manager => el `lifespan` (init_db) NO corre,
  así que el pool nunca abre conexiones reales.
- Se configura API_SHARED_SECRET y se manda el header del proxy para pasar el
  middataware de seguridad.
- El `pool` de los routers se mockea para devolver conteos controlados, de modo
  que probamos 413 (tope de filas) y 429 (rate limit) sin tocar la DB.
"""

import contextlib

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.routers import export as export_router
from app.routers import preview as preview_router
from app.settings import settings

SECRET = "test-secret"
HEADERS = {"x-ideam-proxy-secret": SECRET}
# Payload válido mínimo: datasetId real (Socrata) y un departamento del mapa.
PAYLOAD = {"datasetId": "s54a-sgyg", "departments": ["ANTIOQUIA"]}


class _FakeCursor:
    def __init__(self, one):
        self._one = one

    def fetchone(self):
        return self._one

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, count):
        self._count = count

    def execute(self, sql, *_args, **_kwargs):
        # preview pide un resumen de 7 columnas; el resto pide un único count.
        text = sql if isinstance(sql, str) else ""
        if "count(DISTINCT codigoestacion)" in text:
            return _FakeCursor((self._count, 0, 0, 0, 0, None, None))
        return _FakeCursor((self._count,))


class _FakePool:
    """Reemplazo del ConnectionPool: connection() devuelve un context manager."""

    def __init__(self, count):
        self._count = count

    @contextlib.contextmanager
    def connection(self):
        yield _FakeConn(self._count)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", SECRET)
    ratelimit.reset()
    from app.main import app

    # TestClient SIN `with`: no dispara lifespan (no abre el pool real).
    return TestClient(app)


def test_export_plan_413_cuando_supera_tope_de_filas(client, monkeypatch):
    monkeypatch.setattr(settings, "export_max_rows", 100)
    monkeypatch.setattr(settings, "rate_limit_export_per_hour", 1000)
    # El count devuelve más filas que el tope.
    monkeypatch.setattr(export_router, "pool", _FakePool(count=1_000_000))

    resp = client.post("/api/export-plan", json=PAYLOAD, headers=HEADERS)
    assert resp.status_code == 413
    body = resp.json()
    assert "error" in body
    assert "limite" in body["error"].lower()


def test_export_plan_ok_bajo_tope(client, monkeypatch):
    monkeypatch.setattr(settings, "export_max_rows", 5_000_000)
    monkeypatch.setattr(settings, "rate_limit_export_per_hour", 1000)
    monkeypatch.setattr(export_router, "pool", _FakePool(count=42))

    resp = client.post("/api/export-plan", json=PAYLOAD, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["rowCount"] == 42


def test_export_plan_429_tras_agotar_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_export_per_hour", 3)
    monkeypatch.setattr(settings, "export_max_rows", 5_000_000)
    monkeypatch.setattr(export_router, "pool", _FakePool(count=1))

    # Las primeras 3 pasan; la 4ª es 429.
    for _ in range(3):
        assert client.post("/api/export-plan", json=PAYLOAD, headers=HEADERS).status_code == 200
    resp = client.post("/api/export-plan", json=PAYLOAD, headers=HEADERS)
    assert resp.status_code == 429
    assert "limite" in resp.json()["error"].lower()


def test_rate_limit_es_por_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_export_per_hour", 1)
    monkeypatch.setattr(settings, "export_max_rows", 5_000_000)
    monkeypatch.setattr(export_router, "pool", _FakePool(count=1))

    h1 = {**HEADERS, "cf-connecting-ip": "9.9.9.9"}
    h2 = {**HEADERS, "cf-connecting-ip": "8.8.8.8"}
    assert client.post("/api/export-plan", json=PAYLOAD, headers=h1).status_code == 200
    assert client.post("/api/export-plan", json=PAYLOAD, headers=h1).status_code == 429
    # IP distinta: presupuesto propio.
    assert client.post("/api/export-plan", json=PAYLOAD, headers=h2).status_code == 200


def test_preview_429_tras_agotar_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_catalog_per_hour", 2)
    # preview consulta la DB después del rate-limit; al exceder cortamos antes.
    monkeypatch.setattr(preview_router, "pool", _FakePool(count=0))

    h = {**HEADERS, "cf-connecting-ip": "7.7.7.7"}
    # No nos importa si las primeras fallan por la forma del fake; basta con
    # confirmar que tras N llamadas aparece el 429 del rate-limit.
    statuses = [client.post("/api/preview", json=PAYLOAD, headers=h).status_code for _ in range(5)]
    assert 429 in statuses
    # El 429 debe aparecer DESPUÉS de agotar el presupuesto (no en el 1er hit).
    assert statuses[0] != 429


def test_sin_secreto_de_proxy_es_403(client):
    resp = client.post("/api/export-plan", json=PAYLOAD)  # sin header
    assert resp.status_code == 403

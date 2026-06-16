"""Auditoría: el router `meta` tocaba la DB (meta / date-range / stations.geojson
/ municipalities) SIN rate limit; el único freno era el cache de borde, que las
ráfagas con parámetros rotados saltan y pegan en la hypertable sin tope.

Cada endpoint de lectura del router debe aplicar el gate por-IP del scope
'lectura' (mismo patrón que preview/analytics/catalog_routes) y responder 429 al
agotar el presupuesto. /api/health y /api/ready quedan EXENTOS (son sondas de
salud; un 429 ahí se leería como caída).

Estrategia (igual que test_api_integration): TestClient sin lifespan + pool
mockeado, así se prueba el 429 del rate-limit sin tocar Postgres.
"""

import contextlib

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.routers import meta as meta_router
from app.settings import settings

SECRET = "test-secret"


class _FakeCursor:
    def fetchone(self):
        return (None, None)

    def fetchall(self):
        return []


class _FakeConn:
    def execute(self, *_args, **_kwargs):
        return _FakeCursor()


class _FakePool:
    @contextlib.contextmanager
    def connection(self, *_args, **_kwargs):
        yield _FakeConn()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", SECRET)
    monkeypatch.setattr(settings, "rate_limit_catalog_per_hour", 2)
    monkeypatch.setattr(meta_router, "pool", _FakePool())
    ratelimit.reset()
    from app.main import app

    return TestClient(app)


# Cada caso usa su propia IP para no compartir el presupuesto del scope 'lectura'.
@pytest.mark.parametrize(
    "path",
    [
        "/api/meta",
        "/api/date-range?datasetId=s54a-sgyg",
        "/api/stations.geojson",
        "/api/municipalities?department=ANTIOQUIA",
    ],
)
def test_endpoint_de_lectura_responde_429_tras_agotar_rate_limit(client, path):
    headers = {"x-ideam-proxy-secret": SECRET, "cf-connecting-ip": f"ip-{path}"}
    statuses = [client.get(path, headers=headers).status_code for _ in range(5)]
    assert 429 in statuses, f"{path} nunca devolvió 429 (sin rate limit): {statuses}"
    # El 429 debe aparecer DESPUÉS de agotar el presupuesto, no en el primer hit.
    assert statuses[0] != 429, f"{path} devolvió 429 en el primer hit: {statuses}"


@pytest.mark.parametrize("path", ["/api/health", "/api/ready"])
def test_sondas_de_salud_no_se_rate_limitan(client, path):
    headers = {"cf-connecting-ip": "monitor"}
    # Muchas más llamadas que el límite (2): una sonda NUNCA debe recibir 429.
    statuses = [client.get(path, headers=headers).status_code for _ in range(6)]
    assert 429 not in statuses, f"{path} (sonda de salud) no debe rate-limitarse: {statuses}"

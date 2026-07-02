"""Auditoría 2026-07-01: /api/coverage hacía una query por departamento (N+1,
hasta 40 round-trips por el túnel). Ahora debe resolver TODO con UNA sola query
(ANY de la unión de variantes + GROUP BY) y reagrupar por canónico en Python,
sin cambiar la forma de la respuesta JSON (el Worker la consume tal cual).

TestClient sin lifespan + pool mockeado que registra cada execute: se verifica
el número de round-trips y el reagrupamiento, sin Postgres.
"""

import contextlib

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.routers import catalog_routes
from app.settings import settings

SECRET = "test-secret"
HEADERS = {"x-ideam-proxy-secret": SECRET, "cf-connecting-ip": "5.5.5.5"}

# La query única devuelve las variantes tal como viven en mv_catalogo:
# BOLIVAR aparece con dos grafías históricas que deben reagruparse juntas.
_ROWS = [("ANTIOQUIA", 100), ("BOLIVAR", 40), ("BOLÍVAR", 2)]


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, registro):
        self._registro = registro

    def execute(self, sql, params=None, **_kwargs):
        self._registro.append((sql, params))
        return _FakeCursor(list(_ROWS))


class _FakePool:
    def __init__(self):
        self.executed = []

    @contextlib.contextmanager
    def connection(self, *_args, **_kwargs):
        yield _FakeConn(self.executed)


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(settings, "api_shared_secret", SECRET)
    monkeypatch.setattr(settings, "rate_limit_catalog_per_hour", 1000)
    ratelimit.reset()
    fake_pool = _FakePool()
    monkeypatch.setattr(catalog_routes, "pool", fake_pool)
    from app.main import app

    # TestClient SIN `with`: no dispara lifespan (no abre el pool real).
    return TestClient(app), fake_pool


def test_coverage_usa_una_sola_query_para_varios_departamentos(entorno):
    client, fake_pool = entorno
    payload = {"datasetId": "s54a-sgyg", "departments": ["ANTIOQUIA", "BOLIVAR"]}

    resp = client.post("/api/coverage", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    # Antes: 1 execute POR departamento (N+1). Ahora: exactamente 1 en total.
    assert len(fake_pool.executed) == 1, (
        f"coverage debe hacer UNA query, hizo {len(fake_pool.executed)}"
    )
    sql, params = fake_pool.executed[0]
    # La query única lleva la UNIÓN de variantes de ambos departamentos.
    union = params[1]
    assert "ANTIOQUIA" in union
    assert "BOLIVAR" in union
    assert "BOLÍVAR" in union


def test_coverage_reagrupa_por_canonico_sin_cambiar_la_forma(entorno):
    client, _fake_pool = entorno
    payload = {"datasetId": "s54a-sgyg", "departments": ["ANTIOQUIA", "BOLIVAR"]}

    body = client.post("/api/coverage", json=payload, headers=HEADERS).json()

    # Forma exterior intacta (el Worker la consume).
    assert set(body) == {
        "datasetId", "reports", "stationPoolSize", "queryPlans",
        "totalMatchedRows", "totalUnmatchedRows", "processingMs",
    }
    reports = body["reports"]
    # Un report por canónico, en el orden pedido.
    assert [r["department"] for r in reports] == ["ANTIOQUIA", "BOLIVAR"]
    for report in reports:
        assert set(report) == {
            "department", "configured_variants", "matched", "matched_rows",
            "unmatched_rows", "unmatched_discovered",
        }
    # Reagrupamiento: cada fila cae en el canónico cuyas variantes la contienen.
    antioquia, bolivar = reports
    assert antioquia["matched_rows"] == 100
    assert [m["departamento"] for m in antioquia["matched"]] == ["ANTIOQUIA"]
    # Las dos grafías de BOLIVAR se suman en el mismo report.
    assert bolivar["matched_rows"] == 42
    assert {m["departamento"] for m in bolivar["matched"]} == {"BOLIVAR", "BOLÍVAR"}
    assert {m["normalized"] for m in bolivar["matched"]} == {"BOLIVAR"}
    assert body["totalMatchedRows"] == 142

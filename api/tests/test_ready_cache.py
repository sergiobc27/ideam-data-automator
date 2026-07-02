"""Auditoría 2026-07-01: /api/ready es público (el healthcheck del box lo llama
sin el secreto del proxy) y toca la DB. Exigirle auth rompería la sonda, así
que la mitigación es CACHEAR el resultado del SELECT 1 unos segundos por
proceso: una ráfaga anónima ya no puede consumir conexiones del pool en cada
hit (a lo sumo ~1 sondeo cada _READY_CACHE_SECONDS).

TestClient sin lifespan + pool mockeado que CUENTA los checkouts.
"""

import contextlib
import time

import pytest
from fastapi.testclient import TestClient

from app.routers import meta as meta_router


class _FakeCursor:
    def fetchone(self):
        return (1,)


class _FakeConn:
    def execute(self, *_args, **_kwargs):
        return _FakeCursor()


class _FakePool:
    """Cuenta cuántas veces se toma una conexión (checkouts del pool)."""

    def __init__(self, fallar=False):
        self.checkouts = 0
        self._fallar = fallar

    @contextlib.contextmanager
    def connection(self, *_args, **_kwargs):
        self.checkouts += 1
        if self._fallar:
            raise RuntimeError("db caida")
        yield _FakeConn()


@pytest.fixture
def cliente_sin_lifespan(monkeypatch):
    def _armar(fake_pool):
        monkeypatch.setattr(meta_router, "pool", fake_pool)
        # Estado limpio antes del test; se restaura al final para no
        # contaminar a los demás tests del proceso.
        meta_router._READY_STATE.update({"ok": None, "at": 0.0})
        from app.main import app

        return TestClient(app)

    yield _armar
    meta_router._READY_STATE.update({"ok": None, "at": 0.0})


def test_rafaga_de_ready_sondea_la_db_una_sola_vez(cliente_sin_lifespan):
    fake_pool = _FakePool()
    client = cliente_sin_lifespan(fake_pool)

    statuses = [client.get("/api/ready").status_code for _ in range(10)]
    assert statuses == [200] * 10
    # 10 hits anónimos = 1 solo checkout del pool (el resto sale del cache).
    assert fake_pool.checkouts == 1


def test_expirado_el_cache_vuelve_a_sondear(cliente_sin_lifespan):
    fake_pool = _FakePool()
    client = cliente_sin_lifespan(fake_pool)

    assert client.get("/api/ready").status_code == 200
    assert fake_pool.checkouts == 1
    # Simular que pasó el TTL: el siguiente hit debe sondear de nuevo.
    meta_router._READY_STATE["at"] = time.monotonic() - meta_router._READY_CACHE_SECONDS - 1
    assert client.get("/api/ready").status_code == 200
    assert fake_pool.checkouts == 2


def test_db_caida_devuelve_503_y_tambien_se_cachea(cliente_sin_lifespan):
    fake_pool = _FakePool(fallar=True)
    client = cliente_sin_lifespan(fake_pool)

    statuses = [client.get("/api/ready").status_code for _ in range(5)]
    assert statuses == [503] * 5
    # El fallo también se cachea: la ráfaga no martilla una DB ya caída.
    assert fake_pool.checkouts == 1

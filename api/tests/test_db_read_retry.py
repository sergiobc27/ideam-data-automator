"""Auditoría 2026-07-01: reintento de lecturas idempotentes ante los 502/cortes
transitorios del túnel Cloudflare->box.

`db.read_with_retry` debe reintentar SOLO ante errores de conexión de psycopg
(OperationalError/InterfaceError), nunca ante PoolTimeout (pool agotado no es
un hipo del túnel; reintentar agrava la contención) ni ante errores de
programación (esos son bugs, no transitorios). Sin DB: se prueba con
operaciones falsas que cuentan intentos.
"""

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from app import db


@pytest.fixture(autouse=True)
def sin_espera(monkeypatch):
    """El backoff real (100-300ms) no aporta nada al test: se anula."""
    monkeypatch.setattr(db.time, "sleep", lambda _s: None)


def _operacion_que_falla(veces, exc_factory, resultado="ok"):
    """Operación falsa: falla `veces` veces con exc_factory() y luego retorna."""
    intentos = {"n": 0}

    def operacion():
        intentos["n"] += 1
        if intentos["n"] <= veces:
            raise exc_factory()
        return resultado

    return operacion, intentos


def test_reintenta_operational_error_y_devuelve_el_resultado():
    operacion, intentos = _operacion_que_falla(1, lambda: psycopg.OperationalError("tunel"))
    assert db.read_with_retry(operacion) == "ok"
    assert intentos["n"] == 2  # 1 fallo + 1 reintento exitoso


def test_reintenta_interface_error():
    operacion, intentos = _operacion_que_falla(2, lambda: psycopg.InterfaceError("conexion muerta"))
    assert db.read_with_retry(operacion) == "ok"
    assert intentos["n"] == 3  # falla 2 veces, el tercer intento (último) pasa


def test_se_rinde_tras_agotar_los_intentos():
    operacion, intentos = _operacion_que_falla(99, lambda: psycopg.OperationalError("persistente"))
    with pytest.raises(psycopg.OperationalError):
        db.read_with_retry(operacion)
    assert intentos["n"] == db._READ_ATTEMPTS


def test_no_reintenta_pool_timeout():
    # PoolTimeout es subclase de OperationalError pero significa pool agotado:
    # reintentar solo suma espera y contención. Debe propagarse al primer fallo.
    operacion, intentos = _operacion_que_falla(99, lambda: PoolTimeout("pool agotado"))
    with pytest.raises(PoolTimeout):
        db.read_with_retry(operacion)
    assert intentos["n"] == 1


def test_no_reintenta_errores_no_transitorios():
    operacion, intentos = _operacion_que_falla(99, lambda: psycopg.ProgrammingError("sql roto"))
    with pytest.raises(psycopg.ProgrammingError):
        db.read_with_retry(operacion)
    assert intentos["n"] == 1


def test_sin_fallos_no_hay_reintentos():
    operacion, intentos = _operacion_que_falla(0, lambda: AssertionError("no debe lanzarse"))
    assert db.read_with_retry(operacion) == "ok"
    assert intentos["n"] == 1

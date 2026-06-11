"""Tests unitarios del limitador en memoria (sin DB)."""

from app import ratelimit


def setup_function(_):
    ratelimit.reset()


def test_permite_hasta_el_limite_y_luego_bloquea():
    limit = 5
    for i in range(limit):
        ok, remaining, retry = ratelimit.check_rate_limit("lectura", "1.1.1.1", limit, now=1000.0)
        assert ok is True
        assert remaining == limit - (i + 1)
        assert retry == 0
    # El hit número limit+1 se rechaza con 429 (retry > 0).
    ok, remaining, retry = ratelimit.check_rate_limit("lectura", "1.1.1.1", limit, now=1000.0)
    assert ok is False
    assert remaining == 0
    assert retry > 0


def test_ips_distintas_no_se_pisan():
    limit = 2
    for _ in range(limit):
        assert ratelimit.check_rate_limit("lectura", "a", limit, now=1.0)[0] is True
    assert ratelimit.check_rate_limit("lectura", "a", limit, now=1.0)[0] is False
    # Otra IP sigue con su propio presupuesto.
    assert ratelimit.check_rate_limit("lectura", "b", limit, now=1.0)[0] is True


def test_scopes_distintos_no_se_pisan():
    limit = 1
    assert ratelimit.check_rate_limit("lectura", "x", limit, now=1.0)[0] is True
    assert ratelimit.check_rate_limit("lectura", "x", limit, now=1.0)[0] is False
    # Scope distinto, mismo IP: presupuesto independiente.
    assert ratelimit.check_rate_limit("export", "x", limit, now=1.0)[0] is True


def test_ventana_desliza_y_reinicia():
    limit = 2
    window = 3600
    assert ratelimit.check_rate_limit("lectura", "ip", limit, window, now=0.0)[0] is True
    assert ratelimit.check_rate_limit("lectura", "ip", limit, window, now=10.0)[0] is True
    assert ratelimit.check_rate_limit("lectura", "ip", limit, window, now=20.0)[0] is False
    # Pasada la ventana, el contador se reinicia y vuelve a permitir.
    ok, remaining, retry = ratelimit.check_rate_limit("lectura", "ip", limit, window, now=window + 100.0)
    assert ok is True
    assert remaining == limit - 1
    assert retry == 0


def test_poda_entradas_expiradas_no_crece_sin_tope():
    # Simula rotación de IPs: muchas IPs antiguas + un disparo de poda.
    window = 3600
    # _PRUNE_EVERY hits hacen que la poda se ejecute al menos una vez.
    for i in range(ratelimit._PRUNE_EVERY + 5):
        ratelimit.check_rate_limit("lectura", f"old-{i}", 100, window, now=0.0)
    antes = len(ratelimit._BUCKETS)
    assert antes > 0
    # Una llamada MUY posterior: todas las entradas viejas ya expiraron; la poda
    # (disparada por _PRUNE_EVERY) debe liberarlas en vez de acumularlas.
    for i in range(ratelimit._PRUNE_EVERY):
        ratelimit.check_rate_limit("lectura", f"new-{i}", 100, window, now=window * 10)
    # Solo deberían quedar entradas "new-*" recientes, no las "old-*".
    assert not any(k[1].startswith("old-") for k in ratelimit._BUCKETS), "las entradas expiradas deben podarse"

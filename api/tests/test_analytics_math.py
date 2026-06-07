"""Tests de la matemática pura de hidrología (sin DB): Gumbel, ecuación IDF,
solver 3x3, categorías SPI y normalización de fecha UTC.

Estas funciones sostienen las cifras citables (curvas IDF, períodos de retorno,
SPI); se verifican contra valores calculados a mano y propiedades conocidas.
Importar el router no abre conexiones (el pool es open=False en db.py).
"""

import math
from datetime import datetime, timezone, timedelta

import pytest

from app.routers.analytics import (
    _bucket_date,
    _fit_idf_equation,
    _gumbel_ks_test,
    _gumbel_quantiles,
    _solve_3x3,
    _spi_category,
)


# --- _solve_3x3 ---------------------------------------------------------------

def test_solve_3x3_diagonal():
    # 2x=2, 3y=6, 4z=12 -> (1, 2, 3)
    sol = _solve_3x3([[2, 0, 0], [0, 3, 0], [0, 0, 4]], [2, 6, 12])
    assert sol is not None
    assert all(abs(a - b) < 1e-9 for a, b in zip(sol, [1, 2, 3]))


def test_solve_3x3_general():
    # Sistema con solución conocida (1, 2, -1)
    a = [[1, 1, 1], [0, 2, 1], [1, 0, 2]]
    x = [1, 2, -1]
    c = [a[i][0] * x[0] + a[i][1] * x[1] + a[i][2] * x[2] for i in range(3)]
    sol = _solve_3x3(a, c)
    assert sol is not None
    assert all(abs(s - xi) < 1e-9 for s, xi in zip(sol, x))


def test_solve_3x3_singular_returns_none():
    # Filas linealmente dependientes -> singular -> None
    assert _solve_3x3([[1, 2, 3], [2, 4, 6], [1, 0, 1]], [1, 2, 3]) is None


# --- _gumbel_quantiles --------------------------------------------------------

def test_gumbel_pocos_anios_none():
    assert _gumbel_quantiles([10, 20, 30, 40], (10,)) == (None, {})  # n<5


def test_gumbel_std_cero_none():
    assert _gumbel_quantiles([25, 25, 25, 25, 25], (10,)) == (None, {})


def test_gumbel_valores_conocidos():
    # Serie [10,20,30,40,50]: mean=30, s(n-1)=sqrt(250)=15.8114
    # beta = s*sqrt(6)/pi ; mu = mean - 0.5772*beta
    params, q = _gumbel_quantiles([10, 20, 30, 40, 50], (2, 10, 100))
    assert params is not None
    s = math.sqrt(250)
    beta = s * math.sqrt(6) / math.pi
    mu = 30 - 0.5772156649015329 * beta
    assert abs(params["beta"] - round(beta, 2)) < 0.05
    assert abs(params["mu"] - round(mu, 2)) < 0.05
    # cuantil Tr conocido: x_T = mu - beta*ln(-ln(1-1/T))
    esperado_t10 = mu - beta * math.log(-math.log(1 - 1 / 10))
    assert abs(q[10] - esperado_t10) < 1e-6


def test_gumbel_monotonia():
    # A mayor período de retorno, mayor cuantil.
    _params, q = _gumbel_quantiles([12, 18, 25, 31, 40, 22, 28], (2, 5, 10, 25, 50, 100))
    valores = [q[t] for t in (2, 5, 10, 25, 50, 100)]
    assert valores == sorted(valores)


# --- _gumbel_ks_test ----------------------------------------------------------

def test_ks_test_estructura_y_pocos():
    assert _gumbel_ks_test([10, 20, 30, 40], 20, 5) is None  # n<5
    r = _gumbel_ks_test([10, 20, 30, 40, 50], 22.9, 12.3)
    assert r["test"] == "Kolmogorov-Smirnov"
    assert 0 <= r["statistic"] <= 1
    assert r["critical"] > 0
    assert isinstance(r["passes"], bool)


def test_ks_test_acepta_serie_gumbel():
    # Serie construida desde el cuantil Gumbel exacto (sigue Gumbel por diseño):
    # el test NO debe rechazarla.
    mu, beta = 30.0, 10.0
    n = 25
    maxima = [mu - beta * math.log(-math.log((i - 0.5) / n)) for i in range(1, n + 1)]
    r = _gumbel_ks_test(maxima, mu, beta)
    assert r["passes"] is True
    assert r["statistic"] < r["critical"]


# --- _fit_idf_equation --------------------------------------------------------

def test_fit_idf_pocos_puntos_none():
    assert _fit_idf_equation([(2, 10, 50), (5, 10, 60)]) is None  # <6


def test_fit_idf_recupera_parametros():
    # Datos generados EXACTAMENTE de I = 300 * T^0.25 / D^0.6:
    # el ajuste log-lineal debe recuperar los parámetros con R2~1.
    K, m, n = 300.0, 0.25, 0.6
    samples = []
    for t in (2, 5, 10, 25, 50, 100):
        for d in (10, 30, 60, 120, 360, 1440):
            samples.append((t, d, K * t**m / d**n))
    fit = _fit_idf_equation(samples)
    assert fit is not None
    assert abs(fit["K"] - K) < 1.0
    assert abs(fit["m"] - m) < 0.01
    assert abs(fit["n"] - n) < 0.01
    assert fit["r2"] > 0.999
    assert fit["r2Space"] == "log"


def test_fit_idf_degenerado_finito_o_none():
    # Todos los puntos iguales (sin variación) -> no debe emitir inf/nan.
    fit = _fit_idf_equation([(2, 10, 5.0)] * 8)
    assert fit is None or all(math.isfinite(fit[k]) for k in ("K", "m", "n", "r2"))


# --- _spi_category ------------------------------------------------------------

@pytest.mark.parametrize("z,esperado", [
    (-2.5, "Sequía extrema"),
    (-1.7, "Sequía severa"),
    (-1.2, "Sequía moderada"),
    (0.0, "Normal"),
    (0.9, "Normal"),
    (1.2, "Moderadamente húmedo"),
    (1.7, "Muy húmedo"),
    (2.5, "Extremadamente húmedo"),
])
def test_spi_category(z, esperado):
    assert _spi_category(z) == esperado


# --- _bucket_date (TZ) --------------------------------------------------------

def test_bucket_date_convierte_a_utc():
    # 2026-01-01 23:30 en hora Bogotá (-05) es 2026-01-02 04:30 UTC -> fecha UTC = día 2.
    bogota = timezone(timedelta(hours=-5))
    valor = datetime(2026, 1, 1, 23, 30, tzinfo=bogota)
    assert _bucket_date(valor).isoformat() == "2026-01-02"


def test_bucket_date_ya_utc():
    valor = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    assert _bucket_date(valor).isoformat() == "2026-06-15"

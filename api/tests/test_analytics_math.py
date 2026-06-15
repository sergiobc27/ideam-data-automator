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


def test_return_periods_payload_incluye_bandas_y_reliability():
    from app.routers import analytics
    ys = [{"year": 2000 + i, "maximum": 40.0 + (i % 7) * 3, "days": 365} for i in range(25)]
    p = analytics.build_return_periods_payload(ys, n_boot=200)
    # bandas en cada cuantil de la recomendada
    assert p["quantiles"]
    assert all("lower" in q and "upper" in q for q in p["quantiles"])
    assert all(q["lower"] <= q["value"] <= q["upper"] for q in p["quantiles"])
    # semáforo: 25 años -> amarillo (15<=n<30)
    assert p["reliability"]["level"] == "amarillo"
    assert p["reliability"]["n"] == 25


def test_idf_curves_incluyen_bandas_de_intensidad():
    from app.routers import analytics
    durations = [10, 60, 1440]
    rps = (2, 10, 100)
    # series sintéticas (>=5 puntos) que crecen con la duración
    by_dur = {d: [10.0 + d * 0.01 + (i % 5) for i in range(20)] for d in durations}
    out = analytics.build_idf_curves(by_dur, durations, rps, n_boot=200)
    pts = [p for c in out["curves"] for p in c["points"]]
    assert pts
    assert all("lowerMmH" in p and "upperMmH" in p for p in pts)
    assert all(p["lowerMmH"] <= p["intensityMmH"] <= p["upperMmH"] for p in pts)

import math
import pytest
from app import stationarity as st


def test_independence_r1_valor_conocido():
    # [1,2,3,4]: media=2.5; num = (-1.5)(-0.5)+(-0.5)(0.5)+(0.5)(1.5)=1.25; den=5.0; r1=0.25
    r = st.independence_test([1, 2, 3, 4])
    assert r["test"] == "Autocorrelación lag-1"
    assert abs(r["statistic"] - 0.25) < 1e-9


def test_independence_serie_monotona_falla():
    # Serie creciente larga -> fuerte autocorrelación positiva -> NO pasa.
    r = st.independence_test(list(range(1, 21)))
    assert r["passes"] is False


def test_independence_serie_constante_pasa():
    # Varianza nula -> sin información de correlación -> pasa (guard de /0).
    r = st.independence_test([5.0] * 12)
    assert r["passes"] is True


def test_mk_S_valor_conocido():
    # [3,1,4,1,5]: S calculado a mano = 3.
    r = st.mann_kendall_test([3, 1, 4, 1, 5])
    assert r["statistic"] == 3


def test_mk_creciente():
    r = st.mann_kendall_test(list(range(1, 13)))  # 1..12 estrictamente creciente
    assert r["statistic"] == 66  # n(n-1)/2
    assert r["trend"] == "creciente"
    assert r["passes"] is False


def test_mk_decreciente():
    r = st.mann_kendall_test(list(range(12, 0, -1)))  # 12..1
    assert r["statistic"] == -66
    assert r["trend"] == "decreciente"
    assert r["passes"] is False


def test_mk_constante_sin_tendencia():
    r = st.mann_kendall_test([50.0] * 12)
    assert r["trend"] == "sin tendencia"
    assert r["passes"] is True


def test_average_ranks_sin_empates():
    assert st._average_ranks([10, 30, 20]) == [1.0, 3.0, 2.0]


def test_average_ranks_con_empates():
    assert st._average_ranks([10, 10, 20]) == [1.5, 1.5, 3.0]


def test_pettitt_detecta_salto():
    # Diez 10 seguidos de diez 100: cambio tras la posición 10.
    serie = [10.0] * 10 + [100.0] * 10
    r = st.pettitt_test(serie)
    assert r["test"] == "Pettitt"
    assert r["changePointIndex"] == 10
    assert r["passes"] is False


def test_pettitt_homogenea_pasa():
    r = st.pettitt_test([50.0] * 12)
    assert r["changePointIndex"] is None
    assert r["passes"] is True


def test_report_serie_corta():
    r = st.stationarity_report([1, 2, 3, 4, 5])  # n<10
    assert r["tooShort"] is True
    assert r["stationary"] is None
    assert any("corta" in w for w in r["warnings"])


def test_report_constante_estacionaria():
    r = st.stationarity_report([50.0] * 12)
    assert r["tooShort"] is False
    assert r["stationary"] is True
    assert r["warnings"] == []


def test_report_tendencia_no_estacionaria():
    r = st.stationarity_report(list(range(1, 16)))  # creciente, n=15
    assert r["stationary"] is False
    assert any("Tendencia" in w for w in r["warnings"])
    # los tres sub-bloques presentes
    assert set(["independence", "trend", "changePoint"]).issubset(r)

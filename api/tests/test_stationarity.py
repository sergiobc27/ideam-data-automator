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

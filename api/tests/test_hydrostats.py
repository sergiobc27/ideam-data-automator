import math
import pytest
from app import hydrostats as hs


def test_l_moments_pocos_datos_none():
    assert hs.l_moments([1, 2, 3]) is None  # n<4


def test_l_moments_l1_es_media():
    lm = hs.l_moments([10, 20, 30, 40, 50])
    assert lm is not None
    l1, l2, t3, t4 = lm
    assert abs(l1 - 30.0) < 1e-9  # l1 = media


def test_l_moments_serie_simetrica_t3_cero():
    # Serie perfectamente simétrica -> L-asimetría ~ 0.
    lm = hs.l_moments([10, 20, 30, 40, 50])
    _l1, _l2, t3, _t4 = lm
    assert abs(t3) < 1e-9


def test_l_moments_l2_positivo():
    lm = hs.l_moments([12, 18, 25, 31, 40, 22, 28])
    assert lm is not None
    assert lm[1] > 0


def test_fit_gumbel_recupera_parametros():
    # Serie generada del cuantil Gumbel exacto con mu=30, beta=10:
    # el ajuste por L-momentos debe recuperarlos de forma aproximada.
    mu, beta, n = 30.0, 10.0, 200
    data = [mu - beta * math.log(-math.log((i - 0.5) / n)) for i in range(1, n + 1)]
    g = hs.fit_gumbel(data)
    assert g["name"] == "Gumbel" and g["k"] == 2
    assert abs(g["params"]["mu"] - mu) < 1.5
    assert abs(g["params"]["beta"] - beta) < 1.5


def test_gumbel_quantile_monotonia():
    qs = [hs.quantile_gumbel(1 - 1 / t, 30.0, 10.0) for t in (2, 5, 10, 50, 100)]
    assert qs == sorted(qs)


def test_gumbel_pdf_cdf_coherentes():
    mu, beta = 30.0, 10.0
    # CDF creciente y en (0,1); la pdf integra ~1 por trapecios gruesos.
    assert 0 < hs.cdf_gumbel(20, mu, beta) < hs.cdf_gumbel(40, mu, beta) < 1
    xs = [mu - 60 + i * 0.5 for i in range(int(120 / 0.5))]
    area = sum(hs.pdf_gumbel(x, mu, beta) * 0.5 for x in xs)
    assert abs(area - 1.0) < 0.02

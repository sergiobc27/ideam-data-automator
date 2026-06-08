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


def test_fit_gev_recupera_shape():
    # Datos del cuantil GEV exacto (Hosking) con loc=50, scale=10, shape k=0.15.
    loc, scale, k, n = 50.0, 10.0, 0.15, 300
    data = [loc + (scale / k) * (1 - (-math.log((i - 0.5) / n)) ** k) for i in range(1, n + 1)]
    g = hs.fit_gev(data)
    assert g["name"] == "GEV" and g["k"] == 3
    assert abs(g["params"]["shape"] - k) < 0.05
    assert abs(g["params"]["loc"] - loc) < 2.0
    assert abs(g["params"]["scale"] - scale) < 2.0


def test_gev_quantile_monotonia_y_limite_gumbel():
    # shape ~ 0 debe coincidir con Gumbel.
    q_gev = hs.quantile_gev(1 - 1 / 100, 30.0, 10.0, 0.0)
    q_gum = hs.quantile_gumbel(1 - 1 / 100, 30.0, 10.0)
    assert abs(q_gev - q_gum) < 1e-9
    qs = [hs.quantile_gev(1 - 1 / t, 50.0, 10.0, 0.15) for t in (2, 5, 10, 50, 100)]
    assert qs == sorted(qs)


def test_gev_cdf_fuera_de_soporte():
    # shape>0: cota superior loc + scale/shape -> por encima, CDF=1.
    loc, scale, shape = 50.0, 10.0, 0.2
    upper = loc + scale / shape
    assert hs.cdf_gev(upper + 5, loc, scale, shape) == 1.0


def test_gammp_casos_conocidos():
    # P(a,x) regularizada. P(1,x) = 1 - e^{-x} (exponencial).
    assert abs(hs._gammp(1.0, 1.0) - (1 - math.exp(-1))) < 1e-9
    assert abs(hs._gammp(1.0, 2.0) - (1 - math.exp(-2))) < 1e-9
    # Bordes: P(a,0)=0, y crece a 1.
    assert hs._gammp(3.0, 0.0) == 0.0
    assert hs._gammp(3.0, 100.0) > 0.999
    # Monótona creciente en x.
    assert hs._gammp(2.5, 1.0) < hs._gammp(2.5, 5.0)


def test_fit_lp3_rechaza_no_positivos():
    assert hs.fit_lp3([10, 20, 0, 30, 40]) is None     # contiene 0
    assert hs.fit_lp3([10, 20, -5, 30, 40]) is None    # contiene negativo


def test_lp3_skew_cero_es_lognormal():
    # Logs simétricos -> skewLog~0 -> Wilson-Hilferty K_T = z normal.
    # Cuantil debe coincidir con 10^(meanLog + z*stdLog).
    data = [10 ** v for v in (1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4)]
    f = hs.fit_lp3(data)
    p = 1 - 1 / 100
    z = __import__("statistics").NormalDist().inv_cdf(p)
    esperado = 10 ** (f["params"]["meanLog"] + z * f["params"]["stdLog"])
    assert abs(hs.quantile_lp3(p, **f["params"]) - esperado) < esperado * 0.02


def test_lp3_quantile_monotonia():
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47]
    f = hs.fit_lp3(data)
    qs = [hs.quantile_lp3(1 - 1 / t, **f["params"]) for t in (2, 5, 10, 50, 100)]
    assert qs == sorted(qs)


def test_lp3_cdf_quantile_son_inversas():
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47]
    f = hs.fit_lp3(data)
    for p in (0.2, 0.5, 0.9, 0.99):
        x = hs.quantile_lp3(p, **f["params"])
        assert abs(hs.cdf_lp3(x, **f["params"]) - p) < 0.01


def test_dist_dispatch_coincide_con_funciones_directas():
    # quantile/pdf/cdf por nombre == funciones específicas.
    gp = {"mu": 30.0, "beta": 10.0}
    assert hs.dist_quantile("Gumbel", gp, 0.9) == hs.quantile_gumbel(0.9, **gp)
    assert hs.dist_pdf("Gumbel", gp, 35.0) == hs.pdf_gumbel(35.0, **gp)
    assert hs.dist_cdf("Gumbel", gp, 35.0) == hs.cdf_gumbel(35.0, **gp)


def test_loglik_finita_y_aic():
    data = [12, 18, 25, 31, 40, 22, 28]
    g = hs.fit_gumbel(data)
    ll = hs.loglik("Gumbel", g["params"], data)
    assert math.isfinite(ll)
    a, ll2 = hs.aic("Gumbel", g["params"], data, 2)
    assert abs(ll - ll2) < 1e-9
    assert abs(a - (2 * 2 - 2 * ll)) < 1e-9


def test_loglik_menos_inf_fuera_de_soporte():
    # GEV con cota superior: un dato por encima da densidad 0 -> loglik -inf.
    params = {"loc": 50.0, "scale": 10.0, "shape": 0.3}
    data = [48, 49, 50, 51, 200]  # 200 supera la cota superior
    assert hs.loglik("GEV", params, data) == float("-inf")


def test_ad_ks_statistics_no_negativos():
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47]
    g = hs.fit_gumbel(data)
    assert hs.ad_statistic("Gumbel", g["params"], data) >= 0
    d = hs.ks_statistic("Gumbel", g["params"], data)
    assert 0 <= d <= 1


def test_dist_sample_reproducible():
    # Mismo seed -> misma muestra (clave para reproducibilidad de la tesis).
    rng1 = __import__("random").Random(123)
    rng2 = __import__("random").Random(123)
    p = {"mu": 30.0, "beta": 10.0}
    s1 = [hs.dist_sample("Gumbel", p, rng1) for _ in range(20)]
    s2 = [hs.dist_sample("Gumbel", p, rng2) for _ in range(20)]
    assert s1 == s2


def test_bootstrap_acepta_serie_de_la_dist():
    # Serie generada por la propia Gumbel ajustada: NO debe rechazarse.
    mu, beta, n = 30.0, 10.0, 40
    data = [mu - beta * math.log(-math.log((i - 0.5) / n)) for i in range(1, n + 1)]
    g = hs.fit_gumbel(data)
    res = hs._bootstrap_goodness("Gumbel", g["params"], data, hs.fit_gumbel, n_boot=300)
    assert res["andersonDarling"]["passes"] is True
    assert res["ks"]["passes"] is True


def test_bootstrap_reproducible_mismo_resultado():
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47]
    g = hs.fit_gumbel(data)
    r1 = hs._bootstrap_goodness("Gumbel", g["params"], data, hs.fit_gumbel, n_boot=200)
    r2 = hs._bootstrap_goodness("Gumbel", g["params"], data, hs.fit_gumbel, n_boot=200)
    assert r1 == r2  # semilla derivada de los datos -> determinista

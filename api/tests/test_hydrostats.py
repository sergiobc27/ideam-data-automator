import math
import pytest
from app import hydrostats as hs


def test_l_moments_pocos_datos_none():
    assert hs.l_moments([1, 2, 3]) is None  # n<4


def test_bandas_bootstrap_respetan_techo_fisico():
    # El techo acota la banda bootstrap (excluye cuantiles simulados degenerados),
    # pero la banda siempre envuelve el estimador central; por eso el límite real
    # de upper es max(valor_puntual, techo). Sin el techo, una cola LP3 explosiva
    # dispararía upper muy por encima de ese límite.
    maxima = [80, 95, 110, 70, 130, 90, 150, 60, 105, 120, 85, 140]
    fit = hs.fit_all(maxima, return_periods=(2, 10, 100), goodness=False, bands=True,
                     n_boot=200, max_value=120.0)
    for dist in fit["distributions"]:
        for q in dist["quantiles"]:
            if "upper" in q:
                limite = max(q["value"], 120.0)
                assert q["upper"] <= limite + 1e-9, f"{dist['name']} banda sup {q['upper']} > {limite}"


def test_min_skew_umbral_es_1e2():
    # El umbral de degeneración LP3 quedó en 1e-2 (robustez numérica).
    assert hs._MIN_SKEW == 1e-2


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
    res = hs._bootstrap("Gumbel", g["params"], data, hs.fit_gumbel, n_boot=300)
    assert res["andersonDarling"]["passes"] is True
    assert res["ks"]["passes"] is True


def test_bootstrap_reproducible_mismo_resultado():
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47]
    g = hs.fit_gumbel(data)
    r1 = hs._bootstrap("Gumbel", g["params"], data, hs.fit_gumbel, n_boot=200)
    r2 = hs._bootstrap("Gumbel", g["params"], data, hs.fit_gumbel, n_boot=200)
    assert r1 == r2  # semilla derivada de los datos -> determinista


def test_fit_all_pocos_datos_vacio():
    out = hs.fit_all([10, 20, 30], goodness=False)
    assert out == {"recommended": None, "distributions": []}


def test_fit_all_recomienda_la_correcta():
    # Datos generados de una GEV clara con cola (shape positivo): la
    # recomendada por AIC debe ser GEV (no Gumbel, que subestima la cola).
    loc, scale, k, n = 50.0, 12.0, 0.25, 250
    data = [loc + (scale / k) * (1 - (-math.log((i - 0.5) / n)) ** k) for i in range(1, n + 1)]
    out = hs.fit_all(data, goodness=False)
    assert out["recommended"] == "GEV"
    names = [d["name"] for d in out["distributions"]]
    assert names[0] == "GEV"  # ordenadas por AIC ascendente


def test_fit_all_candidatas_autocontenidas():
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47, 19, 61]
    out = hs.fit_all(data, goodness=False)
    for d in out["distributions"]:
        assert set(d) >= {"name", "k", "params", "logLik", "aic", "quantiles"}
        trs = [q["returnPeriod"] for q in d["quantiles"]]
        assert trs == [2, 5, 10, 25, 50, 100]
        vals = [q["value"] for q in d["quantiles"]]
        assert vals == sorted(vals)  # cuantiles monótonos por Tr


def test_fit_all_goodness_agrega_bloque():
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47, 19, 61]
    out = hs.fit_all(data, goodness=True, n_boot=150)
    assert "goodnessOfFit" in out["distributions"][0]


from app.routers import analytics


def test_build_rp_payload_contrato_no_rompedor():
    valid_years = [{"year": 2000 + i, "maximum": v, "days": 365}
                   for i, v in enumerate([45, 60, 52, 71, 48, 90, 55, 63, 58, 77,
                                          49, 66, 81, 53, 70, 59, 62, 88, 51, 74])]
    out = analytics.build_return_periods_payload(valid_years, n_boot=150)
    # Campos NO-ROMPEDORES presentes y con la forma actual:
    assert out["gumbel"] is not None and {"mu", "beta"} <= set(out["gumbel"])
    assert [q["returnPeriod"] for q in out["quantiles"]] == [2, 5, 10, 25, 50, 100]
    assert {"test", "statistic", "critical", "alpha", "passes"} <= set(out["goodnessOfFit"])
    # Campos NUEVOS:
    assert out["recommended"] in {"Gumbel", "GEV", "LogPearsonIII"}
    assert len(out["distributions"]) >= 1
    # quantiles de nivel superior == los de la recomendada
    rec = next(d for d in out["distributions"] if d["name"] == out["recommended"])
    assert out["quantiles"] == rec["quantiles"]


def test_build_rp_payload_pocos_anios():
    out = analytics.build_return_periods_payload([{"year": 2000, "maximum": 5, "days": 365}])
    assert out["recommended"] is None
    assert out["quantiles"] == [] and out["distributions"] == []


def test_build_idf_curvas_monotonas():
    # by_duration sintético: lámina creciente con D y con el tamaño de muestra
    # suficiente; las curvas resultantes deben ser monótonas (intensidad
    # decrece con D) y no debe activarse el repliegue.
    durations = [10, 30, 60, 120, 360]
    base = {10: 12, 30: 22, 60: 33, 120: 45, 360: 70}
    by_duration = {d: [base[d] * (0.8 + 0.02 * i) for i in range(25)] for d in durations}
    res = analytics.build_idf_curves(by_duration, durations, (2, 5, 10, 25, 50, 100))
    # intensidad estrictamente decreciente con la duración, por cada Tr
    for curve in res["curves"]:
        intens = [p["intensityMmH"] for p in curve["points"]]
        assert intens == sorted(intens, reverse=True)
    assert isinstance(res["chosenByDuration"], dict)
    assert "warnings" in res


def test_build_idf_vacio_si_sin_ajuste():
    by_duration = {10: [5, 5, 5], 30: [6, 6, 6]}  # n<5 y sin dispersión
    res = analytics.build_idf_curves(by_duration, [10, 30], (2, 5, 10))
    assert res["curves"] == []


def test_aviso_exclusion_precip():
    # Sin exclusiones -> None; con exclusiones -> mensaje con el conteo y el umbral.
    assert analytics._aviso_exclusion_precip(0) is None
    assert analytics._aviso_exclusion_precip(-1) is None
    msg = analytics._aviso_exclusion_precip(3)
    assert msg is not None
    assert "3" in msg and "1800" in msg and "no se modifican" in msg


def test_aviso_plausibilidad_precip():
    # Valores normales -> sin aviso.
    assert analytics._aviso_plausibilidad_precip([45.0, 120.0, 300.0, None]) is None
    # Un valor por encima del techo físico (~1800 mm) -> aviso.
    aviso = analytics._aviso_plausibilidad_precip([45.0, 1984.9, 100.0])
    assert aviso is not None and "1800" in aviso


def test_build_idf_avisa_si_lamina_implausible():
    # Lámina absurda en una duración -> el warning de plausibilidad aparece.
    durations = [60, 120]
    by_duration = {60: [2000.0 + i for i in range(25)], 120: [2100.0 + i for i in range(25)]}
    res = analytics.build_idf_curves(by_duration, durations, (2, 5, 10))
    assert any("récord mundial" in w for w in res["warnings"])


def test_build_rp_incluye_stationarity_con_tendencia():
    # 15 años estrictamente crecientes -> stationarityTests presente y tendencia.
    vy = [{"year": 2000 + i, "maximum": float(20 + i), "days": 365} for i in range(15)]
    out = analytics.build_return_periods_payload(vy, n_boot=120)
    assert "stationarityTests" in out
    rep = out["stationarityTests"]
    assert rep["stationary"] is False
    assert rep["trend"]["trend"] == "creciente"
    assert any("Tendencia" in w for w in rep["warnings"])


def test_build_idf_incluye_stationarity_summary_1440():
    # by_duration con clave 1440 con 12 años crecientes -> resumen con tendencia.
    durations = [60, 1440]
    by_duration = {
        60: [30.0 + i for i in range(12)],
        1440: [80.0 + 5 * i for i in range(12)],  # creciente
    }
    res = analytics.build_idf_curves(by_duration, durations, (2, 5, 10))
    assert "stationaritySummary" in res
    assert res["stationaritySummary"] is not None
    assert res["stationaritySummary"]["trend"]["trend"] == "creciente"
    assert any("estacionaria" in w for w in res["warnings"])


def test_build_idf_sin_1440_summary_none():
    # Sin duración 1440 -> summary None, sin warning de estacionariedad.
    durations = [10, 30, 60, 120, 360]
    base = {10: 12, 30: 22, 60: 33, 120: 45, 360: 70}
    by_duration = {d: [base[d] * (0.8 + 0.02 * i) for i in range(25)] for d in durations}
    res = analytics.build_idf_curves(by_duration, durations, (2, 5, 10, 25, 50, 100))
    assert res["stationaritySummary"] is None


def test_bootstrap_bands_envuelven_el_valor():
    # Serie Gumbel exacta; cada cuantil debe traer lower<=value<=upper.
    mu, beta, n = 30.0, 10.0, 40
    data = [mu - beta * math.log(-math.log((i - 0.5) / n)) for i in range(1, n + 1)]
    rec = hs.fit_all(data, goodness=False, bands=True, n_boot=300)["distributions"][0]
    assert rec["quantiles"], "debe haber cuantiles"
    for q in rec["quantiles"]:
        assert "lower" in q and "upper" in q
        assert q["lower"] <= q["value"] <= q["upper"]


def test_bootstrap_bands_reproducible():
    # Semilla derivada de los datos -> mismas bandas entre corridas.
    data = [12, 18, 25, 31, 40, 22, 28, 35, 19, 27, 33, 21]
    a = hs.fit_all(data, goodness=False, bands=True, n_boot=200)["distributions"][0]["quantiles"]
    b = hs.fit_all(data, goodness=False, bands=True, n_boot=200)["distributions"][0]["quantiles"]
    assert [(q["lower"], q["upper"]) for q in a] == [(q["lower"], q["upper"]) for q in b]


def test_bootstrap_bands_mas_anchas_en_tr_altos():
    mu, beta, n = 30.0, 10.0, 40
    data = [mu - beta * math.log(-math.log((i - 0.5) / n)) for i in range(1, n + 1)]
    qs = {q["returnPeriod"]: q
          for q in hs.fit_all(data, goodness=False, bands=True, n_boot=400)["distributions"][0]["quantiles"]}
    assert (qs[100]["upper"] - qs[100]["lower"]) > (qs[2]["upper"] - qs[2]["lower"])


def test_fit_all_sin_bands_no_agrega_lower_upper():
    # Contrato no-rompedor: sin bands=True los cuantiles quedan como antes.
    data = [12, 18, 25, 31, 40, 22, 28, 35, 19, 27, 33, 21]
    rec = hs.fit_all(data, goodness=True, bands=False, n_boot=100)["distributions"][0]
    assert rec["goodnessOfFit"]["ks"] is not None
    assert all("lower" not in q for q in rec["quantiles"])


# --- Desempate por bondad de ajuste cuando el AIC empata (auditoría hidro #5) --

def _cand(name, aic, ks_p=None, ad_stat=None):
    d = {"name": name, "aic": aic}
    if ks_p is not None or ad_stat is not None:
        d["goodnessOfFit"] = {
            "ks": {"pValue": ks_p, "passes": True} if ks_p is not None else None,
            "andersonDarling": {"statistic": ad_stat} if ad_stat is not None else None,
        }
    return d


def test_tiebreak_sin_empate_gana_el_menor_aic():
    # Diferencia de AIC >= 2: manda el AIC aunque la otra tenga mejor KS.
    dists = [_cand("Gumbel", 100.0, ks_p=0.1), _cand("GEV", 103.0, ks_p=0.9)]
    assert hs._recommend_with_gof_tiebreak(dists) == "Gumbel"


def test_tiebreak_con_empate_gana_mejor_ks():
    # AIC dentro de 2 unidades: desempata el mayor p-valor KS.
    dists = [_cand("Gumbel", 100.0, ks_p=0.10), _cand("GEV", 101.5, ks_p=0.80)]
    assert hs._recommend_with_gof_tiebreak(dists) == "GEV"


def test_tiebreak_sin_bondad_mantiene_aic_puro():
    # goodness=False (p.ej. IDF): sin bloque de bondad, AIC puro.
    dists = [_cand("Gumbel", 100.0), _cand("GEV", 100.5)]
    assert hs._recommend_with_gof_tiebreak(dists) == "Gumbel"


def test_tiebreak_empate_de_ks_desempata_por_ad():
    # Mismo p-valor KS: gana el A^2 de Anderson-Darling MENOR.
    dists = [_cand("Gumbel", 100.0, ks_p=0.5, ad_stat=0.9),
             _cand("GEV", 101.0, ks_p=0.5, ad_stat=0.3)]
    assert hs._recommend_with_gof_tiebreak(dists) == "GEV"


def test_fit_all_recommended_sigue_en_distributions():
    # La recomendada (con o sin desempate) siempre es una candidata real.
    data = [12, 18, 25, 31, 40, 22, 28, 55, 33, 47, 19, 61]
    out = hs.fit_all(data, goodness=True, n_boot=150)
    assert out["recommended"] in {d["name"] for d in out["distributions"]}
    # y las distribuciones siguen ordenadas por AIC ascendente (contrato).
    aics = [d["aic"] for d in out["distributions"]]
    assert aics == sorted(aics)


def test_selection_criterion_expuesto():
    # Nota de honestidad: cuasi-AIC sobre L-momentos, con desempate KS/AD.
    assert "cuasi-AIC" in hs.SELECTION_CRITERION
    assert "L-momentos" in hs.SELECTION_CRITERION
    vy = [{"year": 2000 + i, "maximum": v, "days": 365}
          for i, v in enumerate([45, 60, 52, 71, 48, 90, 55, 63, 58, 77])]
    out = analytics.build_return_periods_payload(vy, n_boot=120)
    assert out["selectionCriterion"] == hs.SELECTION_CRITERION


# --- Bondad de ajuste por duración en IDF (auditoría hidro #6) -----------------

def test_build_idf_goodness_apagado_por_defecto():
    durations = [10, 30]
    by_duration = {d: [10.0 * d / 10 + i for i in range(12)] for d in durations}
    res = analytics.build_idf_curves(by_duration, durations, (2, 5, 10))
    assert res["goodnessByDuration"] == {}


def test_build_idf_goodness_ks_por_duracion():
    durations = [10, 30, 60]
    base = {10: 12, 30: 22, 60: 33}
    by_duration = {d: [base[d] * (0.8 + 0.02 * i) for i in range(25)] for d in durations}
    res = analytics.build_idf_curves(by_duration, durations, (2, 5, 10),
                                     goodness=True, gof_n_boot=120)
    assert set(res["goodnessByDuration"]) == set(durations)
    for dur, gof in res["goodnessByDuration"].items():
        assert gof["distribution"] == res["chosenByDuration"][dur]
        assert {"statistic", "critical", "pValue", "alpha", "passes"} <= set(gof)
    # Si alguna duración no pasa KS, debe haber un warning que la nombre.
    for dur, gof in res["goodnessByDuration"].items():
        if not gof["passes"]:
            assert any(f"{dur} min" in w and "KS" in w for w in res["warnings"])

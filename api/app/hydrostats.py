"""Estadística de extremos en Python puro (sin numpy/scipy).

Ajusta Gumbel y GEV por L-momentos (Hosking & Wallis, 1997) y Log-Pearson III
por momentos de log10 + factor de frecuencia Wilson-Hilferty (Chow; Bulletin
17B; Manual de Drenaje INVÍAS). Recomienda una distribución por AIC y mide la
bondad de ajuste (Anderson-Darling y KS-Lilliefors) por bootstrap paramétrico
con semilla fija (reproducible). El módulo no toca la DB; lo consume
app.routers.analytics."""

import math
import random
import statistics

_EULER = 0.5772156649015329
_LN10 = math.log(10.0)
_NORMAL = statistics.NormalDist()
# |skew| por debajo de este umbral: la LP3 degenera a lognormal. Subido de 1e-3
# a 1e-2 por robustez numérica: con skew minúsculo, alpha=4/skew² explota y el
# factor Wilson-Hilferty se vuelve inestable (auditoría 2026-06-15).
_MIN_SKEW = 1e-2
# Techo físico de precipitación diaria (récord mundial 24 h ~1825 mm): un cuantil
# bootstrap por encima es un remuestreo degenerado; se excluye de las bandas de
# confianza para que la banda superior no muestre valores imposibles.
_MAX_PHYSICAL_MM = 1800.0


def l_moments(sample):
    """L-momentos muestrales por PWM insesgados (Hosking & Wallis).
    Devuelve (l1, l2, t3, t4) con t3=L-asimetría, t4=L-curtosis, o None si
    n<4 o l2<=0 (sin dispersión utilizable)."""
    x = sorted(sample)
    n = len(x)
    if n < 4:
        return None
    b0 = sum(x) / n
    b1 = sum(j * x[j] for j in range(n)) / (n * (n - 1))
    b2 = sum(j * (j - 1) * x[j] for j in range(n)) / (n * (n - 1) * (n - 2))
    b3 = sum(j * (j - 1) * (j - 2) * x[j] for j in range(n)) / (n * (n - 1) * (n - 2) * (n - 3))
    l1 = b0
    l2 = 2 * b1 - b0
    l3 = 6 * b2 - 6 * b1 + b0
    l4 = 20 * b3 - 30 * b2 + 12 * b1 - b0
    if l2 <= 0:
        return None
    return (l1, l2, l3 / l2, l4 / l2)


def fit_gumbel(maxima):
    """Gumbel (EV1) por L-momentos: beta = l2/ln2, mu = l1 - gamma*beta."""
    lm = l_moments(maxima)
    if lm is None:
        return None
    l1, l2, _t3, _t4 = lm
    beta = l2 / math.log(2.0)
    if beta <= 0:
        return None
    return {"name": "Gumbel", "k": 2, "params": {"mu": l1 - _EULER * beta, "beta": beta}}


def quantile_gumbel(p, mu, beta):
    """Cuantil para no-excedencia p (= 1 - 1/T)."""
    return mu - beta * math.log(-math.log(p))


def pdf_gumbel(x, mu, beta):
    z = (x - mu) / beta
    return math.exp(-z - math.exp(-z)) / beta


def cdf_gumbel(x, mu, beta):
    return math.exp(-math.exp(-(x - mu) / beta))


def fit_gev(maxima):
    """GEV por L-momentos (aproximación de Hosking). Parametrización:
    x(p) = loc + (scale/k)*(1 - (-ln p)^k); k = forma (shape)."""
    lm = l_moments(maxima)
    if lm is None:
        return None
    l1, l2, t3, _t4 = lm
    c = 2.0 / (3.0 + t3) - math.log(2.0) / math.log(3.0)
    k = 7.8590 * c + 2.9554 * c * c
    if abs(k) < 1e-6:  # límite Gumbel
        g = fit_gumbel(maxima)
        if g is None:
            return None
        p = g["params"]
        return {"name": "GEV", "k": 3, "params": {"loc": p["mu"], "scale": p["beta"], "shape": 0.0}}
    gam = math.gamma(1.0 + k)
    denom = (1.0 - 2.0 ** (-k)) * gam
    if denom == 0:
        return None
    scale = l2 * k / denom
    if scale <= 0:
        return None
    loc = l1 - scale * (1.0 - gam) / k
    return {"name": "GEV", "k": 3, "params": {"loc": loc, "scale": scale, "shape": k}}


def quantile_gev(p, loc, scale, shape):
    if abs(shape) < 1e-6:
        return loc - scale * math.log(-math.log(p))
    return loc + (scale / shape) * (1.0 - (-math.log(p)) ** shape)


def pdf_gev(x, loc, scale, shape):
    if abs(shape) < 1e-6:
        return pdf_gumbel(x, loc, scale)
    y = 1.0 - shape * (x - loc) / scale
    if y <= 0:
        return 0.0
    return (y ** (1.0 / shape - 1.0)) * math.exp(-(y ** (1.0 / shape))) / scale


def cdf_gev(x, loc, scale, shape):
    if abs(shape) < 1e-6:
        return cdf_gumbel(x, loc, scale)
    y = 1.0 - shape * (x - loc) / scale
    if y <= 0:
        return 1.0 if shape > 0 else 0.0  # k>0: por encima de la cota superior
    return math.exp(-(y ** (1.0 / shape)))


def _gammp(a, x):
    """Función gamma incompleta inferior regularizada P(a,x) (Numerical
    Recipes): serie para x<a+1, fracción continua para x>=a+1. Pura."""
    if x < 0 or a <= 0:
        return float("nan")
    if x == 0:
        return 0.0
    if x < a + 1.0:  # serie
        ap = a
        s = 1.0 / a
        delta = s
        for _ in range(500):
            ap += 1.0
            delta *= x / ap
            s += delta
            if abs(delta) < abs(s) * 1e-14:
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    # fracción continua para Q(a,x) = 1 - P(a,x)
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delt = d * c
        h *= delt
        if abs(delt - 1.0) < 1e-14:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return 1.0 - q


def fit_lp3(maxima):
    """Log-Pearson III: momentos (media, desv., asimetría) de log10(x).
    El cuantil usa el factor de frecuencia Wilson-Hilferty (Bulletin 17B /
    INVÍAS). Requiere x>0 en toda la serie."""
    if any(v <= 0 for v in maxima):
        return None
    y = [math.log10(v) for v in maxima]
    n = len(y)
    if n < 4:
        return None
    my = statistics.fmean(y)
    sy = statistics.stdev(y)
    if sy <= 0:
        return None
    m3 = sum((v - my) ** 3 for v in y) / n
    skew = (n * n) / ((n - 1) * (n - 2)) * m3 / (sy ** 3)
    return {"name": "LogPearsonIII", "k": 3,
            "params": {"meanLog": my, "stdLog": sy, "skewLog": skew}}


def _wilson_hilferty_kt(p, skewLog):
    z = _NORMAL.inv_cdf(p)
    if abs(skewLog) < _MIN_SKEW:
        return z
    kk = skewLog / 6.0
    return (2.0 / skewLog) * (((z - kk) * kk + 1.0) ** 3 - 1.0)


def quantile_lp3(p, meanLog, stdLog, skewLog):
    return 10.0 ** (meanLog + _wilson_hilferty_kt(p, skewLog) * stdLog)


def _pe3_params(meanLog, stdLog, skewLog):
    """Parámetros Pearson III (forma alpha, escala beta, posición xi) desde
    los momentos de los logaritmos."""
    alpha = 4.0 / (skewLog * skewLog)
    beta = stdLog * skewLog / 2.0
    xi = meanLog - 2.0 * stdLog / skewLog
    return alpha, beta, xi


def pdf_lp3(x, meanLog, stdLog, skewLog):
    if x <= 0:
        return 0.0
    y = math.log10(x)
    if abs(skewLog) < _MIN_SKEW:
        dens_y = statistics.NormalDist(meanLog, stdLog).pdf(y)
    else:
        alpha, beta, xi = _pe3_params(meanLog, stdLog, skewLog)
        w = (y - xi) / beta
        if w <= 0:
            return 0.0
        ln_dens = (alpha - 1.0) * math.log(w) - w - math.log(abs(beta)) - math.lgamma(alpha)
        dens_y = math.exp(ln_dens)
    return dens_y / (x * _LN10)


def cdf_lp3(x, meanLog, stdLog, skewLog):
    if x <= 0:
        return 0.0
    y = math.log10(x)
    if abs(skewLog) < _MIN_SKEW:
        return statistics.NormalDist(meanLog, stdLog).cdf(y)
    alpha, beta, xi = _pe3_params(meanLog, stdLog, skewLog)
    w = (y - xi) / beta
    if w <= 0:
        return 0.0 if beta > 0 else 1.0
    p = _gammp(alpha, w)
    return p if beta > 0 else 1.0 - p


def dist_quantile(name, params, p):
    if name == "Gumbel":
        return quantile_gumbel(p, params["mu"], params["beta"])
    if name == "GEV":
        return quantile_gev(p, params["loc"], params["scale"], params["shape"])
    return quantile_lp3(p, params["meanLog"], params["stdLog"], params["skewLog"])


def dist_pdf(name, params, x):
    if name == "Gumbel":
        return pdf_gumbel(x, params["mu"], params["beta"])
    if name == "GEV":
        return pdf_gev(x, params["loc"], params["scale"], params["shape"])
    return pdf_lp3(x, params["meanLog"], params["stdLog"], params["skewLog"])


def dist_cdf(name, params, x):
    if name == "Gumbel":
        return cdf_gumbel(x, params["mu"], params["beta"])
    if name == "GEV":
        return cdf_gev(x, params["loc"], params["scale"], params["shape"])
    return cdf_lp3(x, params["meanLog"], params["stdLog"], params["skewLog"])


def loglik(name, params, data):
    total = 0.0
    for x in data:
        d = dist_pdf(name, params, x)
        if d <= 0 or not math.isfinite(d):
            return float("-inf")
        total += math.log(d)
    return total


def aic(name, params, data, k):
    """AIC = 2k - 2*loglik. La verosimilitud se evalúa en los estimadores
    L-momento / de-momentos (cuasi-AIC: no es MLE; criterio RELATIVO de
    selección). Devuelve (aic, loglik)."""
    ll = loglik(name, params, data)
    if not math.isfinite(ll):
        return float("inf"), ll
    return 2 * k - 2 * ll, ll


def ad_statistic(name, params, data):
    """Anderson-Darling A^2 (pondera colas) contra la CDF ajustada."""
    x = sorted(data)
    n = len(x)
    s = 0.0
    for i, xi in enumerate(x, start=1):
        u = min(max(dist_cdf(name, params, xi), 1e-12), 1 - 1e-12)
        u_comp = min(max(dist_cdf(name, params, x[n - i]), 1e-12), 1 - 1e-12)
        s += (2 * i - 1) * (math.log(u) + math.log(1 - u_comp))
    return -n - s / n


def ks_statistic(name, params, data):
    """Kolmogorov-Smirnov D contra la CDF ajustada."""
    x = sorted(data)
    n = len(x)
    d = 0.0
    for i, xi in enumerate(x, start=1):
        u = dist_cdf(name, params, xi)
        d = max(d, i / n - u, u - (i - 1) / n)
    return d


def dist_sample(name, params, rng):
    """Una observación simulada de la distribución (para el bootstrap)."""
    if name == "LogPearsonIII":
        my, sy, g = params["meanLog"], params["stdLog"], params["skewLog"]
        if abs(g) < _MIN_SKEW:
            y = rng.gauss(my, sy)
        else:
            alpha, beta, xi = _pe3_params(my, sy, g)
            y = xi + beta * rng.gammavariate(alpha, 1.0)
        return 10.0 ** y
    u = rng.random() or 1e-12  # evita u=0 -> log(0) en los cuantiles EV
    return dist_quantile(name, params, u)


def _percentile(sorted_vals, p):
    """Percentil p (0..100) por interpolación lineal sobre una lista ORDENADA."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _bootstrap(name, params, data, fit_fn, return_periods=(), n_boot=1000,
               want_goodness=True, want_bands=False, alpha=0.05, band_alpha=0.10,
               max_value=_MAX_PHYSICAL_MM):
    """Bootstrap paramétrico de UNA pasada (Lilliefors generalizado). Por cada
    remuestreo simula desde la distribución ajustada, la reajusta y mide:
    (a) AD/KS para la bondad de ajuste; (b) el cuantil por período de retorno
    para las bandas de confianza (percentiles band_alpha/2 y 1-band_alpha/2 ->
    P5/P95 para ~90%). Semilla derivada de los datos -> reproducible. Devuelve
    solo lo solicitado: {'andersonDarling','ks'} y/o {'bands': {T:{lower,upper}}}."""
    n = len(data)
    obs_ad = ad_statistic(name, params, data)
    obs_ks = ks_statistic(name, params, data)
    seed = (n * 1000003 + int(round(sum(data) * 100))) % (2 ** 31)
    rng = random.Random(seed)
    ad_null, ks_null = [], []
    q_null = {t: [] for t in return_periods}
    for _ in range(n_boot):
        sample = [dist_sample(name, params, rng) for _ in range(n)]
        refit = fit_fn(sample)
        if refit is None:
            continue
        rp = refit["params"]
        if want_goodness:
            ad_null.append(ad_statistic(name, rp, sample))
            ks_null.append(ks_statistic(name, rp, sample))
        if want_bands:
            for t in return_periods:
                q = dist_quantile(name, rp, 1.0 - 1.0 / t)
                # Techo físico: un cuantil simulado por encima del récord mundial
                # es un remuestreo degenerado (cola LP3 explosiva); excluirlo evita
                # bandas de confianza con valores imposibles.
                if math.isfinite(q) and 0 <= q <= max_value:
                    q_null[t].append(q)

    def summarize(obs, null):
        if not null:
            return None
        null_sorted = sorted(null)
        m = len(null_sorted)
        idx = min(m - 1, int(math.ceil((1 - alpha) * m)) - 1)
        crit = null_sorted[idx]
        pval = sum(1 for v in null if v >= obs) / m
        return {"statistic": round(obs, 4), "critical": round(crit, 4),
                "pValue": round(pval, 4), "alpha": alpha, "passes": bool(obs < crit)}

    out = {}
    if want_goodness:
        out["andersonDarling"] = summarize(obs_ad, ad_null)
        out["ks"] = summarize(obs_ks, ks_null)
    if want_bands:
        lo_p, hi_p = 100.0 * band_alpha / 2.0, 100.0 * (1.0 - band_alpha / 2.0)
        bands = {}
        for t in return_periods:
            vals = sorted(q_null[t])
            lo, hi = _percentile(vals, lo_p), _percentile(vals, hi_p)
            if lo is not None and hi is not None:
                bands[t] = {"lower": round(lo, 1), "upper": round(hi, 1)}
        out["bands"] = bands
    return out


RETURN_PERIODS = (2, 5, 10, 25, 50, 100)
_FITTERS = (("Gumbel", fit_gumbel, 2), ("GEV", fit_gev, 3), ("LogPearsonIII", fit_lp3, 3))
# Función de ajuste por nombre de distribución (para recomputar bondad de una
# distribución concreta, p.ej. la elegida por duración en IDF).
FIT_FUNCTIONS = {name: fn for name, fn, _k in _FITTERS}

# Umbral de "empate" de AIC (Burnham & Anderson, 2002): modelos dentro de 2
# unidades de AIC tienen SOPORTE EQUIVALENTE. Aquí es doblemente pertinente porque
# el AIC de aic() es un CUASI-AIC (verosimilitud en estimadores L-momento/de-
# momentos, no MLE), luego su diferencia fina no es concluyente.
_AIC_TIE_DELTA = 2.0
# Texto de honestidad para exponer en la API: el criterio de selección NO es un
# AIC formal por MLE.
SELECTION_CRITERION = (
    "cuasi-AIC sobre ajustes por L-momentos (Gumbel/GEV) y momentos-log (LP3); "
    "es un criterio relativo, no un AIC por máxima verosimilitud. Ante empate "
    "(diferencia de AIC < 2) se desempata por bondad de ajuste (KS/Anderson-Darling)."
)


def _recommend_with_gof_tiebreak(dists):
    """Distribución recomendada: la de MENOR AIC, con DESEMPATE por bondad de
    ajuste cuando el AIC no distingue (ΔAIC < 2). Regla estándar (Burnham &
    Anderson, 2002): entre modelos con soporte equivalente por AIC se prefiere el
    de mejor ajuste empírico (mayor p-valor KS; A^2 de Anderson-Darling menor como
    segundo criterio), usando la bondad ya calculada por bootstrap. Sin bloque de
    bondad (goodness=False, p.ej. IDF) se mantiene el AIC puro. `dists` debe venir
    ordenada por AIC ascendente."""
    best_aic = dists[0]["aic"]
    empatadas = [d for d in dists if d["aic"] <= best_aic + _AIC_TIE_DELTA]
    con_gof = [d for d in empatadas if (d.get("goodnessOfFit") or {}).get("ks")]
    if len(con_gof) < 2:
        return dists[0]["name"]  # sin empate real o sin bondad calculada -> AIC puro

    def _clave(d):
        gof = d.get("goodnessOfFit") or {}
        ks = gof.get("ks") or {}
        ad = gof.get("andersonDarling") or {}
        p = ks.get("pValue")
        a2 = ad.get("statistic")
        # mayor p-valor KS = mejor; A^2 menor desempata.
        return (p if p is not None else -1.0,
                -(a2 if a2 is not None else float("inf")))

    return max(con_gof, key=_clave)["name"]


def fit_all(maxima, return_periods=RETURN_PERIODS, goodness=True, bands=False, n_boot=1000,
            max_value=_MAX_PHYSICAL_MM):
    """Ajusta Gumbel, GEV y LP3; descarta las degeneradas; ordena por AIC y
    marca la recomendada (menor AIC). Cada candidata es autocontenida
    (params, logLik, aic, cuantiles por Tr, bondad si goodness=True, y bandas
    de confianza ~90% en cada cuantil si bands=True)."""
    candidates = []
    for name, fit_fn, k in _FITTERS:
        fitted = fit_fn(maxima)
        if fitted is None:
            continue
        params = fitted["params"]
        a, ll = aic(name, params, maxima, k)
        if not math.isfinite(a):
            continue
        quantiles, ok = [], True
        for t in return_periods:
            q = dist_quantile(name, params, 1.0 - 1.0 / t)
            if not math.isfinite(q) or q < 0:
                ok = False
                break
            quantiles.append({"returnPeriod": t, "value": round(q, 1)})
        if not ok:
            continue
        cand = {
            "name": name, "k": k,
            "params": {kk: round(vv, 4) for kk, vv in params.items()},
            "logLik": round(ll, 3), "aic": round(a, 3), "quantiles": quantiles,
        }
        if goodness or bands:
            boot = _bootstrap(name, params, maxima, fit_fn, return_periods,
                              n_boot=n_boot, want_goodness=goodness, want_bands=bands,
                              max_value=max_value)
            if goodness:
                cand["goodnessOfFit"] = {"andersonDarling": boot.get("andersonDarling"),
                                         "ks": boot.get("ks")}
            if bands:
                band_map = boot.get("bands", {})
                for q in cand["quantiles"]:
                    b = band_map.get(q["returnPeriod"])
                    if b:
                        # clamp: la banda SIEMPRE envuelve el estimador central
                        # (el percentil bootstrap puede sesgarse en colas).
                        q["lower"] = min(b["lower"], q["value"])
                        q["upper"] = max(b["upper"], q["value"])
        candidates.append((a, cand))
    if not candidates:
        return {"recommended": None, "distributions": []}
    candidates.sort(key=lambda c: c[0])
    dists = [c[1] for c in candidates]
    # `distributions` queda ordenada por AIC ascendente (contrato existente); la
    # recomendada es la de menor AIC salvo empate (ΔAIC<2), donde desempata la
    # bondad de ajuste ya calculada (auditoría hidrología #5).
    return {"recommended": _recommend_with_gof_tiebreak(dists), "distributions": dists}

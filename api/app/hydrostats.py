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

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

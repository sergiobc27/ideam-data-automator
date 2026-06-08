"""Pruebas previas de estacionariedad sobre la serie de máximos anuales
(Python puro, sin numpy/scipy). Los ajustes de extremos (hydrostats) asumen
que la serie es estacionaria — independiente, sin tendencia y homogénea. Aquí
diagnosticamos esa suposición y AVISAMOS; no se cambia ni se bloquea el cálculo.

Pruebas: independencia (autocorrelación lag-1, Anderson 1942), tendencia
(Mann-Kendall, WMO/Kendall 1975) y punto de cambio (Pettitt 1979). α=0.05."""

import math
import statistics
from collections import Counter

_NORMAL = statistics.NormalDist()


def independence_test(values, alpha=0.05):
    """Autocorrelación de lag-1 (Anderson). Bajo independencia r1 ~ N(E, V) con
    E=-1/(n-1), V=(n-2)/(n-1)^2. passes=True si no hay correlación serial."""
    n = len(values)
    mean = sum(values) / n
    denom = sum((x - mean) ** 2 for x in values)
    if denom == 0:
        return {"test": "Autocorrelación lag-1", "statistic": 0.0, "pValue": 1.0, "passes": True}
    num = sum((values[t] - mean) * (values[t + 1] - mean) for t in range(n - 1))
    r1 = num / denom
    e = -1.0 / (n - 1)
    v = (n - 2) / ((n - 1) ** 2)
    z = (r1 - e) / math.sqrt(v) if v > 0 else 0.0
    p = min(1.0, max(0.0, 2.0 * (1.0 - _NORMAL.cdf(abs(z)))))
    return {"test": "Autocorrelación lag-1", "statistic": round(r1, 3),
            "pValue": round(p, 4), "passes": p >= alpha}


def mann_kendall_test(values, alpha=0.05):
    """Tendencia monótona (Mann-Kendall, no paramétrico). S con corrección por
    empates; Z y p-valor por aproximación normal. passes=True si no hay
    tendencia significativa."""
    n = len(values)
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            d = values[j] - values[i]
            s += (d > 0) - (d < 0)
    tie_term = sum(t * (t - 1) * (2 * t + 5) for t in Counter(values).values() if t > 1)
    var = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var <= 0:
        return {"test": "Mann-Kendall", "statistic": s, "z": 0.0, "pValue": 1.0,
                "trend": "sin tendencia", "passes": True}
    if s > 0:
        z = (s - 1) / math.sqrt(var)
    elif s < 0:
        z = (s + 1) / math.sqrt(var)
    else:
        z = 0.0
    p = min(1.0, max(0.0, 2.0 * (1.0 - _NORMAL.cdf(abs(z)))))
    if p < alpha:
        trend = "creciente" if s > 0 else "decreciente"
    else:
        trend = "sin tendencia"
    return {"test": "Mann-Kendall", "statistic": s, "z": round(z, 3), "pValue": round(p, 4),
            "trend": trend, "passes": trend == "sin tendencia"}


def _average_ranks(values):
    """Rangos 1-based con promedio en empates."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # promedio de los rangos (i+1)..(j+1)
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pettitt_test(values, alpha=0.05):
    """Punto de cambio (Pettitt, no paramétrico) vía la forma de rangos
    U_t = 2*sum(rangos[:t]) - t*(n+1). K=max|U_t|; p≈2*exp(-6K^2/(n^3+n^2)).
    passes=True si NO hay cambio significativo. changePointIndex = nº de datos
    en el primer segmento (1..n-1) si es significativo, si no None."""
    n = len(values)
    ranks = _average_ranks(values)
    cum = 0.0
    best_abs, best_t = -1.0, 0
    for t in range(1, n):  # tamaño del primer segmento
        cum += ranks[t - 1]
        u = 2.0 * cum - t * (n + 1)
        if abs(u) > best_abs:
            best_abs, best_t = abs(u), t
    k = best_abs
    p = min(1.0, max(0.0, 2.0 * math.exp(-6.0 * k * k / (n ** 3 + n ** 2))))
    significant = p < alpha
    return {"test": "Pettitt", "statistic": round(k, 2), "pValue": round(p, 4),
            "changePointIndex": best_t if significant else None,
            "passes": not significant}

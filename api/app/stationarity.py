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

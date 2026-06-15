"""El umbral de "año válido" (días con dato) debe ser UNO solo y valer 300 en
las tres rutas que lo usaban por separado (analytics, reliability, batch).

Antes desincronizaban: reliability usaba 330, las otras 300. Ahora todas
referencian la MISMA constante compartida (`reliability._DIAS_MIN_ANIO_VALIDO`)
para que no vuelvan a divergir. Decisión del dueño del proyecto: 300.
"""

from app import reliability as rel
from app.services import fiabilidad_batch as batch


def test_constante_compartida_vale_300():
    assert rel._DIAS_MIN_ANIO_VALIDO == 300


def test_reliability_referencia_la_constante_compartida():
    # reliability mide completitud con la MISMA constante (no un 330 propio).
    assert rel._DIAS_MIN_ANIO is rel._DIAS_MIN_ANIO_VALIDO


def test_batch_referencia_la_constante_compartida():
    assert batch._DIAS_MIN_ANIO is rel._DIAS_MIN_ANIO_VALIDO


def test_reliability_clasifica_segun_la_constante():
    # Un año con días == constante-1 es INCOMPLETO; con días == constante es completo.
    bajo = rel._DIAS_MIN_ANIO_VALIDO - 1
    ys = [{"year": 2000 + i, "maximum": 50.0, "days": 365} for i in range(34)]
    ys.append({"year": 2099, "maximum": 50.0, "days": bajo})
    r = rel.reliability_report(ys, {"stationary": True})
    assert r["incompleteYears"] == 1
    # Y si el año tiene exactamente la constante, cuenta como completo.
    ys[-1]["days"] = rel._DIAS_MIN_ANIO_VALIDO
    r2 = rel.reliability_report(ys, {"stationary": True})
    assert r2["incompleteYears"] == 0

"""Auditoría TZ (residual): build_filters acotaba el rango de fecha del crudo
(`observaciones`) con fechas LOCALES naive (startDate T00:00:00 y endDate
T23:59:59.999). En la sesión America/Bogota eso son las 05:00 UTC, mientras que
los datos y el resto del read-side (caggs.py, preview._resumen_desde_agregado)
usan UTC medio-abierto. El desajuste recortaba/desplazaba ~5h en el borde del
día: el resumen (UTC) y las filas crudas (local) discrepaban.

build_filters debe alinear el rango a UTC medio-abierto [start, end+1día), igual
que preview.py:109-115 y caggs.py:55-59."""

from app.models import QueryPayload
from app.normalize import build_filters


def _payload(**kw):
    return QueryPayload(datasetId="s54a-sgyg", departments=["ANTIOQUIA"], **kw)


def test_startDate_se_bindea_a_medianoche_utc():
    _where, params, _ds, _c = build_filters(_payload(startDate="2024-11-15"))
    assert params["start"] == "2024-11-15T00:00:00+00:00"


def test_endDate_es_exclusivo_a_medianoche_utc_del_dia_siguiente():
    where, params, _ds, _c = build_filters(_payload(endDate="2024-11-15"))
    # Medio-abierto: < medianoche UTC del día SIGUIENTE incluye todo el día 15.
    assert params["end"] == "2024-11-16T00:00:00+00:00"
    assert "fechaobservacion < %(end)s" in where
    # No debe quedar el <= inclusivo viejo (desalineaba el borde).
    assert "fechaobservacion <= %(end)s" not in where


def test_rango_completo_coherente_con_la_ruta_cagg():
    where, params, _ds, _c = build_filters(
        _payload(startDate="2024-01-01", endDate="2024-01-31")
    )
    assert params["start"] == "2024-01-01T00:00:00+00:00"
    assert params["end"] == "2024-02-01T00:00:00+00:00"
    assert "fechaobservacion >= %(start)s" in where
    assert "fechaobservacion < %(end)s" in where

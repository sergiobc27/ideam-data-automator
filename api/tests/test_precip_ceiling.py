"""Fix #1: el techo de precipitación debe cubrir TAMBIÉN min/max.

Para precip, `valor_min`/`valor_max` son extremos POR LECTURA (10 min); una
lectura corrupta/centinela inflaba `valor_max` con picos imposibles que se
colaban en la serie (timeseries metric=min/max) y en la climatología mensual.
El filtro de fila debe aplicar sobre la COLUMNA que se agrega, no sobre
`valor_sum`, y con el techo físico por lectura (diario, no mensual).
"""

from app.routers import analytics
from app.routers.analytics import (
    _MAX_PRECIP_DIARIA_MM,
    _MAX_PRECIP_MENSUAL_MM,
    _precip_ceiling_clause,
)


# --- _precip_ceiling_clause: columna y techo correctos por métrica ------------

def test_sum_filtra_por_valor_sum_con_techo_del_bucket():
    # metric=sum: el acumulado del bucket; techo del bucket (mensual/diario).
    clause, ceiling = _precip_ceiling_clause("sum", "obs_mensual")
    assert "valor_sum <=" in clause
    assert ceiling == _MAX_PRECIP_MENSUAL_MM

    clause_d, ceiling_d = _precip_ceiling_clause("sum", "obs_diario")
    assert "valor_sum <=" in clause_d
    assert ceiling_d == _MAX_PRECIP_DIARIA_MM


def test_max_filtra_por_valor_max_con_techo_por_lectura():
    # metric=max agrega max(valor_max): debe filtrar valor_max (no valor_sum),
    # y el extremo POR LECTURA no puede superar el techo físico DIARIO.
    clause, ceiling = _precip_ceiling_clause("max", "obs_mensual")
    assert "valor_max <=" in clause
    assert "valor_sum" not in clause
    assert ceiling == _MAX_PRECIP_DIARIA_MM


def test_min_filtra_por_valor_min_con_techo_por_lectura():
    clause, ceiling = _precip_ceiling_clause("min", "obs_mensual")
    assert "valor_min <=" in clause
    assert "valor_sum" not in clause
    assert ceiling == _MAX_PRECIP_DIARIA_MM


# --- monthly-climatology: para precip min/max NO exponen extremos sin tope ----

def test_monthly_climatology_omite_min_max_para_precip(monkeypatch):
    """Para precip, los campos `min`/`max` (extremos por lectura, sin tope) se
    omiten; la información correcta y capada vive en monthlyDepthMin/Max."""
    import contextlib

    # Fila simulada del cagg: la quinta/sexta columnas (min(valor_min),
    # max(valor_max)) traen un pico imposible que NO debe aflorar como min/max.
    fila = (1, 12.3, 0.1, 99999.0, 1000, 250.0, 80.0, 480.0)

    class _Cur:
        def fetchall(self):
            return [fila]

    class _Conn:
        def execute(self, *a, **k):
            return _Cur()

    class _Pool:
        @contextlib.contextmanager
        def connection(self):
            yield _Conn()

    monkeypatch.setattr(analytics, "pool", _Pool())

    class _Payload:
        datasetId = analytics._PRECIP_DATASET
        departments = ["ANTIOQUIA"]
        catalogFilters = None
        startDate = None
        endDate = None

    out = analytics.monthly_climatology(_Payload())
    mes = out["months"][0]
    # Precip: min/max por lectura se omiten (None); el pico 99999 no aflora.
    assert mes["min"] is None
    assert mes["max"] is None
    # La lámina mensual capada (monthlyDepth*) sí está presente.
    assert mes["monthlyDepth"] == 250.0
    assert mes["monthlyDepthMin"] == 80.0
    assert mes["monthlyDepthMax"] == 480.0


def test_monthly_climatology_conserva_min_max_para_no_precip(monkeypatch):
    """Para datasets NO precip (p.ej. temperatura), min/max son significativos y
    deben conservarse."""
    import contextlib

    fila = (1, 18.0, 5.0, 32.0, 1000, None, None, None)

    class _Cur:
        def fetchall(self):
            return [fila]

    class _Conn:
        def execute(self, *a, **k):
            return _Cur()

    class _Pool:
        @contextlib.contextmanager
        def connection(self):
            yield _Conn()

    monkeypatch.setattr(analytics, "pool", _Pool())

    class _Payload:
        datasetId = "s54a-XXXX"   # cualquier id != precip
        departments = ["ANTIOQUIA"]
        catalogFilters = None
        startDate = None
        endDate = None

    # get_dataset valida el id; usamos un dataset real no-precip.
    from app.catalog import DATASETS
    no_precip = next(d["id"] for d in DATASETS if d["id"] != analytics._PRECIP_DATASET)
    _Payload.datasetId = no_precip

    out = analytics.monthly_climatology(_Payload())
    mes = out["months"][0]
    assert mes["min"] == 5.0
    assert mes["max"] == 32.0

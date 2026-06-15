"""Fix #2: /api/stations.geojson no debe ser un full-table scan sin cota.

El catálogo (~18K estaciones) se materializaba sin LIMIT: riesgo de OOM en el
box pequeño. Debe llevar un tope explícito MUY por encima del conteo actual
(guarda de seguridad, no un recorte funcional)."""

import contextlib

from app.routers import meta


def test_geojson_lleva_limit_con_cota_alta(monkeypatch):
    capturado = {}

    class _Cur:
        def fetchall(self):
            return []

    class _Conn:
        def execute(self, sql, *a, **k):
            capturado["sql"] = sql
            return _Cur()

    class _Pool:
        @contextlib.contextmanager
        def connection(self, *a, **k):
            yield _Conn()

    monkeypatch.setattr(meta, "pool", _Pool())
    meta.stations_geojson()

    sql = capturado["sql"]
    assert "LIMIT" in sql.upper()
    # La cota debe estar MUY por encima del catálogo actual (~18K).
    assert meta._STATIONS_GEOJSON_CAP >= 30000
    assert str(meta._STATIONS_GEOJSON_CAP) in sql

"""Fix #3: el techo de fecha de /api/preview (mitigación del scan profundo en
datasets que terminaron en el pasado) debe aplicarse en el caso COMÚN: hay
filas pero el usuario no acotó endDate. Antes la lógica estaba inline y era
fácil que ese caso quedara sin cubrir.

El techo se OMITE solo cuando ya hay una cota: el usuario dio endDate (param
'end' presente) o no hay datos (end is None)."""

from datetime import datetime, timedelta, timezone

from app.routers.preview import _preview_techo_clause


_END = datetime(2020, 6, 30, tzinfo=timezone.utc)


def test_aplica_techo_cuando_hay_filas_y_sin_endDate():
    # Caso común: end (max de obs_diario) presente y el usuario NO dio endDate.
    techo, extra = _preview_techo_clause(_END, params={"dataset_id": "x"})
    assert techo  # cláusula no vacía
    assert "fechaobservacion <" in techo
    assert extra["preview_techo"] == _END + timedelta(days=1)


def test_omite_techo_cuando_el_usuario_dio_endDate():
    # build_filters ya puso 'end' en params: el rango del usuario acota el scan.
    techo, extra = _preview_techo_clause(_END, params={"end": "2020-06-30T23:59:59.999"})
    assert techo == ""
    assert extra == {}


def test_omite_techo_cuando_no_hay_datos():
    techo, extra = _preview_techo_clause(None, params={"dataset_id": "x"})
    assert techo == ""
    assert extra == {}

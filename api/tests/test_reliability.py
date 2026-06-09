from app import reliability as rel


def _years(n, days=365):
    return [{"year": 2000 + i, "maximum": 50.0 + i, "days": days} for i in range(n)]


STAT_OK = {"stationary": True}
STAT_BAD = {"stationary": False}


def test_verde_largo_completo_estacionario():
    r = rel.reliability_report(_years(35), STAT_OK)
    assert r["level"] == "verde"
    assert r["n"] == 35 and r["incompleteYears"] == 0


def test_amarillo_por_longitud_media():
    assert rel.reliability_report(_years(20), STAT_OK)["level"] == "amarillo"


def test_rojo_por_registro_corto():
    assert rel.reliability_report(_years(10), STAT_OK)["level"] == "rojo"


def test_completitud_baja_un_nivel():
    # 35 años (verde por longitud) pero 20% incompletos -> amarillo.
    ys = _years(28) + [{"year": 2100 + i, "maximum": 60.0, "days": 100} for i in range(7)]
    r = rel.reliability_report(ys, STAT_OK)
    assert r["incompleteYears"] == 7
    assert r["level"] == "amarillo"


def test_no_estacionaria_baja_un_nivel():
    assert rel.reliability_report(_years(35), STAT_BAD)["level"] == "amarillo"


def test_doble_degradacion_verde_a_rojo():
    ys = _years(28) + [{"year": 2100 + i, "maximum": 60.0, "days": 100} for i in range(7)]
    assert rel.reliability_report(ys, STAT_BAD)["level"] == "rojo"


def test_piso_en_rojo():
    assert rel.reliability_report(_years(10), STAT_BAD)["level"] == "rojo"


def test_borde_n_30_es_verde():
    assert rel.reliability_report(_years(30), STAT_OK)["level"] == "verde"


def test_borde_n_15_es_amarillo():
    assert rel.reliability_report(_years(15), STAT_OK)["level"] == "amarillo"


def test_reasons_no_vacio_cuando_no_verde():
    assert len(rel.reliability_report(_years(10), STAT_BAD)["reasons"]) >= 1

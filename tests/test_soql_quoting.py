"""TDD del escape de literales SoQL (fix: inyección / ruptura por comillas).

Un código de estación o un valor de filtro con comilla simple debe quedar
ESCAPADO (comilla doblada) en la cláusula SoQL, sin romper la consulta ni
permitir inyección. Las fechas (ISO, internas) también pasan por quote_soql.
"""

import unittest

from ideam_socrata import engine
from ideam_socrata.query_validation import (
    quote_soql,
    date_window_clauses,
    in_clause_upper,
    discover_department_values,
)


class QuoteSoqlTests(unittest.TestCase):
    def test_dobla_comilla_simple(self):
        self.assertEqual(quote_soql("O'BRIEN"), "'O''BRIEN'")

    def test_valor_normal_sin_cambios(self):
        self.assertEqual(quote_soql("ATLANTICO"), "'ATLANTICO'")


class ConstruirTareasQuotingTests(unittest.TestCase):
    """El IN-list de codigoestacion debe escapar comillas en los códigos."""

    def test_codigo_con_comilla_se_escapa(self):
        tareas = engine.construir_tareas(
            None, None, [], {"ABC'123"}, None
        )
        # un solo bloque de filtros; la cláusula IN debe llevar la comilla doblada
        _anio, _mes, filtros = tareas[0]
        clausula = next(f for f in filtros if f.startswith("codigoestacion IN"))
        self.assertIn("'ABC''123'", clausula)
        # y NO debe quedar la comilla sin escapar (que cerraría el literal)
        self.assertNotIn("'ABC'123'", clausula)

    def test_codigo_normal_va_entre_comillas(self):
        tareas = engine.construir_tareas(None, None, [], {"0021195190"}, None)
        _a, _m, filtros = tareas[0]
        clausula = next(f for f in filtros if f.startswith("codigoestacion IN"))
        self.assertIn("'0021195190'", clausula)


class AvanzadosInClauseTests(unittest.TestCase):
    """El IN-list de filtros avanzados (upper(col) IN (...)) debe escapar comillas."""

    def test_valor_con_comilla_se_escapa(self):
        clausula = engine._in_clause_avanzado("corriente", ["RIO D'OR"])
        self.assertIn("'RIO D''OR'", clausula)
        self.assertTrue(clausula.startswith("upper(corriente) IN ("))

    def test_valor_normal(self):
        clausula = engine._in_clause_avanzado("estado", ["activa"])
        self.assertIn("'ACTIVA'", clausula)


class DateWindowClausesTests(unittest.TestCase):
    """La ventana de fechas [inicio, fin) debe escapar los literales de fecha
    (mismo patrón que usan tools.py y el comando de verificación CLI)."""

    def test_construye_ventana(self):
        self.assertEqual(
            date_window_clauses("fechaobservacion", "2020-01-01", "2020-12-31"),
            [
                "fechaobservacion >= '2020-01-01T00:00:00.000'",
                "fechaobservacion < '2020-12-31T00:00:00.000'",
            ],
        )

    def test_escapa_comilla_en_fecha(self):
        clausulas = date_window_clauses("f", "x' OR 1=1 --", "y")
        # La comilla hostil queda doblada dentro del literal (no lo cierra).
        self.assertEqual(clausulas[0], "f >= 'x'' OR 1=1 --T00:00:00.000'")


class InClauseUpperTests(unittest.TestCase):
    """Helper compartido `upper(col) IN (...)` — cada valor ESCAPADO.

    Lo usan engine (filtros avanzados) y main (asistente interactivo); antes
    main concatenaba comillas crudas, lo que rompía/inyectaba con valores como
    ``RIO D'OR``.
    """

    def test_escapa_comilla_en_valor(self):
        self.assertEqual(
            in_clause_upper("corriente", ["RIO D'OR"]),
            "upper(corriente) IN ('RIO D''OR')",
        )

    def test_varios_valores_se_unen_y_escapan(self):
        self.assertEqual(
            in_clause_upper("municipio", ["soledad", "santa fe'"]),
            "upper(municipio) IN ('SOLEDAD', 'SANTA FE''')",
        )


class _FakeSocrataClient:
    """Cliente falso que captura los kwargs de `.get` (incl. el `where`)."""

    def __init__(self):
        self.captured = {}

    def get(self, dataset_id, **kwargs):
        self.captured = dict(kwargs)
        self.captured["dataset_id"] = dataset_id
        return []


def _passthrough_retry(fn, _label):
    return fn()


class DiscoverDepartmentLikeTests(unittest.TestCase):
    """El LIKE de `discover_department_values` debe escapar la comilla del needle."""

    def test_escapa_comilla_en_el_like(self):
        client = _FakeSocrataClient()
        discover_department_values(client, "abcd-1234", _passthrough_retry, department="O'X")
        where = client.captured["where"]
        # La comilla queda doblada dentro del literal (no lo cierra ni inyecta).
        self.assertIn("O''X", where)
        self.assertNotIn("'%O'X%'", where)


if __name__ == "__main__":
    unittest.main()

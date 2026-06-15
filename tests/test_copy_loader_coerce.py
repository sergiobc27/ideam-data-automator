"""TDD del saneo de filas COPY (fix CRITICO: una fila mala abortaba el lote).

`_coerce_row_for_copy` toma una fila (tupla en el orden de STAGING_COLUMNS) y
devuelve (fila_segura | None, motivo). None => la fila se desvia a
observaciones_rechazos en vez de envenenar el COPY/transaccion.
"""

import math
import unittest

import pandas as pd

from ideam_socrata.db import copy_loader as cl


def _row(**overrides):
    """Construye una fila valida en el orden de STAGING_COLUMNS y aplica overrides."""
    base = {
        "floating_id_hex": "ab",
        "source_dataset_id": "s54a-sgyg",
        "codigoestacion": "0001",
        "codigosensor": "01",
        "fechaobservacion": pd.Timestamp("2024-01-01T00:00:00"),
        "valorobservado": 12.5,
        "nombreestacion": "X",
        "departamento": "ATLANTICO",
        "municipio": "BARRANQUILLA",
        "zonahidrografica": "Z",
        "latitud": 10.0,
        "longitud": -74.0,
        "descripcionsensor": "d",
        "unidadmedida": "mm",
    }
    base.update(overrides)
    return tuple(base[c] for c in cl.STAGING_COLUMNS)


class CoerceRowTests(unittest.TestCase):
    def _idx(self, col):
        return cl.STAGING_COLUMNS.index(col)

    def test_fila_normal_pasa_sin_cambios(self):
        row = _row()
        safe, motivo = cl._coerce_row_for_copy(row)
        self.assertIsNone(motivo)
        self.assertEqual(safe, row)

    def test_fecha_nat_se_rechaza(self):
        safe, motivo = cl._coerce_row_for_copy(_row(fechaobservacion=pd.NaT))
        self.assertIsNone(safe)
        self.assertIsNotNone(motivo)

    def test_fecha_none_se_rechaza(self):
        # fechaobservacion es NOT NULL en el esquema: sin fecha no hay fila valida.
        safe, motivo = cl._coerce_row_for_copy(_row(fechaobservacion=None))
        self.assertIsNone(safe)
        self.assertIsNotNone(motivo)

    def test_valor_no_finito_se_anula_pero_la_fila_sobrevive(self):
        for malo in (float("inf"), float("-inf"), float("nan")):
            safe, motivo = cl._coerce_row_for_copy(_row(valorobservado=malo))
            self.assertIsNotNone(safe, f"la fila debe sobrevivir con {malo}")
            self.assertIsNone(motivo)
            self.assertIsNone(safe[self._idx("valorobservado")])

    def test_valor_none_es_hueco_legitimo(self):
        safe, motivo = cl._coerce_row_for_copy(_row(valorobservado=None))
        self.assertIsNotNone(safe)
        self.assertIsNone(motivo)
        self.assertIsNone(safe[self._idx("valorobservado")])

    def test_string_gigante_se_trunca_no_aborta(self):
        gigante = "x" * 5000
        safe, motivo = cl._coerce_row_for_copy(_row(nombreestacion=gigante))
        self.assertIsNotNone(safe)
        self.assertIsNone(motivo)
        self.assertLessEqual(len(safe[self._idx("nombreestacion")]), cl._MAX_TEXT_LEN)

    def test_codigoestacion_faltante_se_rechaza(self):
        # codigoestacion es NOT NULL y clave del floating_id.
        safe, motivo = cl._coerce_row_for_copy(_row(codigoestacion=None))
        self.assertIsNone(safe)
        self.assertIsNotNone(motivo)


class _RecordingCopy:
    """Imita el context-manager de cur.copy(): registra write_row."""

    def __init__(self):
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write_row(self, row):
        self.rows.append(row)


class _FakeCursor:
    def __init__(self):
        self.executed = []
        self.executemany_calls = []
        self.copy_obj = _RecordingCopy()
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))

    def copy(self, sql):
        return self.copy_obj


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed = True


class LoadDataframeDivertsBadRowTests(unittest.TestCase):
    """Fix CRITICO: una fila no-COPY-safe NO debe abortar el lote; se desvia a
    observaciones_rechazos y el resto se carga."""

    def setUp(self):
        cl._ALTITUDES = {}  # evita SELECT de altitudes

    def test_fila_con_fecha_nat_no_aborta_y_se_desvia(self):
        df = pd.DataFrame(
            {
                "floating_id": ["aa", "bb"],
                "source_dataset_id": ["s54a-sgyg", "s54a-sgyg"],
                "codigoestacion": ["0001", "0002"],
                "codigosensor": ["01", "01"],
                "fechaobservacion": [pd.Timestamp("2024-01-01"), pd.NaT],
                "valorobservado": [10.0, 11.0],
                "nombreestacion": ["A", "B"],
                "departamento": ["ATLANTICO", "ATLANTICO"],
                "municipio": ["X", "Y"],
                "zonahidrografica": ["Z", "Z"],
                "latitud": [10.0, 10.0],
                "longitud": [-74.0, -74.0],
                "descripcionsensor": ["d", "d"],
                "unidadmedida": ["mm", "mm"],
            }
        )
        cur = _FakeCursor()
        conn = _FakeConn(cur)
        cl.load_dataframe(conn, df, mode="insert")

        # Solo la fila buena llega al COPY.
        self.assertEqual(len(cur.copy_obj.rows), 1)
        # La fila con NaT se desvio a rechazos.
        self.assertEqual(len(cur.executemany_calls), 1)
        _sql, rows = cur.executemany_calls[0]
        self.assertEqual(len(rows), 1)
        self.assertTrue(conn.committed)


if __name__ == "__main__":
    unittest.main()

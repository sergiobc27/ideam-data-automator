import unittest

import pandas as pd

from ideam_socrata import physical_ranges as pr
from ideam_socrata.db import copy_loader as cl


class _FakeCursor:
    def __init__(self):
        self.executemany_calls = []

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))


class SanitizeTests(unittest.TestCase):
    def setUp(self):
        # Evita la consulta de altitudes a la DB en _sanitize.
        cl._ALTITUDES = {}

    def _frame(self, dataset_id, valores):
        frame = pd.DataFrame(
            {
                "floating_id_hex": [f"{i:02x}" for i in range(len(valores))],
                "source_dataset_id": [dataset_id] * len(valores),
                "codigoestacion": ["0001"] * len(valores),
                "valorobservado": valores,
                "unidadmedida": ["u"] * len(valores),
            }
        )
        return frame.reindex(columns=cl.STAGING_COLUMNS)

    def test_sanitize_aparta_precip_imposible_y_conserva_null(self):
        ok, bad = cl._sanitize(None, self._frame(pr.PRECIP_ID, [10.0, -9999.0, None]))
        self.assertEqual(len(ok), 2)  # 10.0 y None (hueco legítimo)
        self.assertEqual(len(bad), 1)
        self.assertIn("motivo", bad.columns)

    def test_sanitize_defensivo_dataset_sin_reglas(self):
        ok, bad = cl._sanitize(None, self._frame("xxxx-yyyy", [1e9, -1e9]))
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(bad), 0)

    def test_record_rejections_arma_filas_con_jsonb(self):
        frame = pd.DataFrame(
            {
                "source_dataset_id": [pr.PRECIP_ID],
                "valorobservado": [-9999.0],
                "fechaobservacion": [pd.Timestamp("2024-01-01T00:00:00Z")],
                "motivo": ["fuera de rango"],
            }
        )
        cur = _FakeCursor()
        cl._record_rejections(cur, frame)
        self.assertEqual(len(cur.executemany_calls), 1)
        _sql, rows = cur.executemany_calls[0]
        self.assertEqual(rows[0][0], pr.PRECIP_ID)   # source_dataset_id
        self.assertEqual(rows[0][2], "fuera de rango")  # motivo


if __name__ == "__main__":
    unittest.main()

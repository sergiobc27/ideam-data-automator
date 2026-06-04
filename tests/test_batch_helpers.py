import unittest

import pandas as pd

from ideam_socrata.batch import _validar_departamentos, _validar_fechas, month_blocks
from ideam_socrata.transform import parse_export_dates


class ValidacionesTests(unittest.TestCase):
    def test_typo_sugiere_correccion(self):
        with self.assertRaises(SystemExit) as ctx:
            _validar_departamentos(["BOLIBAR"])
        self.assertIn("BOLIVAR", str(ctx.exception))

    def test_acepta_variantes_con_tilde_y_minusculas(self):
        self.assertEqual(_validar_departamentos(["atlántico"]), ["ATLANTICO"])

    def test_canoniza_y_deduplica(self):
        self.assertEqual(
            _validar_departamentos(["BOGOTA", "BOGOTÁ D.C."]), ["BOGOTA D.C."]
        )

    def test_fecha_malformada(self):
        with self.assertRaises(SystemExit) as ctx:
            _validar_fechas("2024-99-01", "2024-02-01")
        self.assertIn("YYYY-MM-DD", str(ctx.exception))

    def test_rango_invertido(self):
        with self.assertRaises(SystemExit) as ctx:
            _validar_fechas("2024-06-01", "2024-01-01")
        self.assertIn("ANTERIOR", str(ctx.exception))

    def test_rango_valido_pasa(self):
        self.assertIsNone(_validar_fechas("2024-01-01", "2024-06-01"))


class MonthBlocksTests(unittest.TestCase):
    def test_single_month(self):
        self.assertEqual(month_blocks("2024-01-01", "2024-01-31"), [(2024, 1)])

    def test_year_boundary(self):
        blocks = month_blocks("2023-11-15", "2024-02-01")
        self.assertEqual(blocks, [(2023, 11), (2023, 12), (2024, 1), (2024, 2)])

    def test_multi_year_count(self):
        blocks = month_blocks("2020-01-01", "2022-12-31")
        self.assertEqual(len(blocks), 36)


class ParseExportDatesTests(unittest.TestCase):
    def test_us_format(self):
        serie = pd.Series(["11/15/2024 10:20:00 PM", "01/02/2020 12:00:00 AM"])
        parsed = parse_export_dates(serie)
        self.assertEqual(parsed.iloc[0].strftime("%Y-%m-%dT%H:%M:%S"), "2024-11-15T22:20:00")
        self.assertEqual(parsed.iloc[1].strftime("%Y-%m-%dT%H:%M:%S"), "2020-01-02T00:00:00")

    def test_iso_fallback(self):
        serie = pd.Series(["2024-11-15T22:20:00.000"])
        parsed = parse_export_dates(serie)
        self.assertEqual(parsed.iloc[0].strftime("%Y-%m-%dT%H:%M:%S"), "2024-11-15T22:20:00")

    def test_invalid_becomes_nat(self):
        serie = pd.Series(["no-es-fecha", None])
        parsed = parse_export_dates(serie)
        self.assertTrue(parsed.isna().all())

    def test_parity_us_vs_iso(self):
        """El mismo instante por ambas rutas debe producir el MISMO string
        normalizado (clave para que floating_id sea identico)."""
        us = parse_export_dates(pd.Series(["06/04/2026 01:30:00 PM"]))
        iso = parse_export_dates(pd.Series(["2026-06-04T13:30:00.000"]))
        self.assertEqual(
            us.iloc[0].strftime("%Y-%m-%dT%H:%M:%S"),
            iso.iloc[0].strftime("%Y-%m-%dT%H:%M:%S"),
        )


if __name__ == "__main__":
    unittest.main()

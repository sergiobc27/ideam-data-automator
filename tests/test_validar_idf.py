"""Tests del helper de validacion IDF 1-a-1 (scripts/validar_idf.py).

La correctitud del MAPE importa para la tesis: si el numero esta mal, la
conclusion de validacion esta mal."""

import sys
import unittest
from pathlib import Path

# El script vive en scripts/ (no en el paquete), lo agregamos al path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import validar_idf as v  # noqa: E402


class ValidarIdfTests(unittest.TestCase):
    def test_error_relativo_simetrico(self):
        self.assertAlmostEqual(v.error_relativo_pct(100, 110), 10.0)
        self.assertAlmostEqual(v.error_relativo_pct(100, 90), 10.0)

    def test_oficial_cero_es_error(self):
        with self.assertRaises(ValueError):
            v.error_relativo_pct(0, 5)

    def test_mape_global_y_omite_filas_incompletas(self):
        rows = [
            {"estacion": "A", "duracion_min": "60", "Tr_anios": "10",
             "I_oficial_mmh": "100", "I_plataforma_mmh": "110"},   # 10%
            {"estacion": "A", "duracion_min": "30", "Tr_anios": "10",
             "I_oficial_mmh": "50", "I_plataforma_mmh": "60"},     # 20%
            {"estacion": "B", "duracion_min": "60", "Tr_anios": "10",
             "I_oficial_mmh": "", "I_plataforma_mmh": "80"},        # incompleta -> omitida
        ]
        res = v.compute_validation(rows)
        self.assertEqual(res["n"], 2)
        self.assertAlmostEqual(res["mape_global"], 15.0)           # (10+20)/2
        self.assertAlmostEqual(res["mape_por_estacion"]["A"], 15.0)
        self.assertAlmostEqual(res["mape_por_duracion"]["60"], 10.0)
        self.assertAlmostEqual(res["mape_por_duracion"]["30"], 20.0)

    def test_sin_datos_devuelve_n_cero(self):
        res = v.compute_validation([
            {"estacion": "A", "duracion_min": "60", "Tr_anios": "10",
             "I_oficial_mmh": "", "I_plataforma_mmh": ""},
        ])
        self.assertEqual(res["n"], 0)
        self.assertIsNone(res["mape_global"])

    def test_veredicto_por_umbral(self):
        self.assertIn("EXCELENTE", v.veredicto(10.0))
        self.assertIn("PUBLICABLE", v.veredicto(18.0))
        self.assertIn("REVISAR", v.veredicto(25.0))
        self.assertIn("SIN DATOS", v.veredicto(None))


if __name__ == "__main__":
    unittest.main()

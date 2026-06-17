"""Tests de las funciones puras de scripts/generar_comparacion_idf.py.

La formula de I_oficial y el armado de filas alimentan la validacion de la
tesis: si estan mal, el MAPE de las estaciones nuevas estaria mal."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generar_comparacion_idf as g  # noqa: E402


class IntensidadOficialTests(unittest.TestCase):
    def test_tibaitata_10min_tr2_coincide_con_csv(self):
        # Coeficientes de Gonzalez para TIBAITATA (cruce) -> el CSV de las 13
        # estaciones tiene I_oficial=75.39 para 10 min, Tr=2.
        i = g.intensidad_oficial_mmh(tau=332.72, rho=0.25, d0=0.0, mu=0.72,
                                     dur_min=10, tr_anios=2)
        self.assertAlmostEqual(i, 75.39, delta=0.1)

    def test_d0_desplaza_la_duracion(self):
        # Con d0>0 la intensidad baja (denominador mayor).
        sin_d0 = g.intensidad_oficial_mmh(170.0, 0.37, 0.0, 0.54, 10, 2)
        con_d0 = g.intensidad_oficial_mmh(170.0, 0.37, 2.56, 0.54, 10, 2)
        self.assertLess(con_d0, sin_d0)


class FiltrarEstacionesTests(unittest.TestCase):
    def setUp(self):
        self.cruce = [
            {"codigo_ideam": "A", "nombre": "A", "anios_plataforma": 17, "mu": 0.72},  # >=15, fuera de rango
            {"codigo_ideam": "B", "nombre": "B", "anios_plataforma": 14, "mu": 0.55},  # dentro
            {"codigo_ideam": "C", "nombre": "C", "anios_plataforma": 12, "mu": 0.30},  # mu bajo, fuera
            {"codigo_ideam": "D", "nombre": "D", "anios_plataforma": 9, "mu": 0.60},   # registro corto, fuera
            {"codigo_ideam": "E", "nombre": "E", "anios_plataforma": 10, "mu": 0.51},  # dentro (borde)
        ]

    def test_filtra_por_anios_y_mu(self):
        sel = g.filtrar_estaciones(self.cruce, 10, 14, 0.50)
        self.assertEqual({e["codigo_ideam"] for e in sel}, {"B", "E"})

    def test_min_mu_es_exclusivo(self):
        # mu exactamente 0.50 NO entra (umbral exclusivo).
        cruce = [{"codigo_ideam": "X", "nombre": "X", "anios_plataforma": 12, "mu": 0.50}]
        self.assertEqual(g.filtrar_estaciones(cruce, 10, 14, 0.50), [])


class FilasEstacionTests(unittest.TestCase):
    def setUp(self):
        self.est = {"codigo_ideam": "21206990", "nombre": "TIBAITATA - AUT",
                    "tau": 332.72, "rho": 0.25, "d0": 0.0, "mu": 0.72}

    def test_nombre_csv(self):
        self.assertEqual(g.nombre_csv(self.est), "TIBAITATA_-_AUT_21206990")

    def test_no_disponible_devuelve_vacio(self):
        self.assertEqual(g.filas_estacion(self.est, {"available": False, "curves": []}), [])

    def test_combina_y_filtra_duraciones_fuera_de_grilla(self):
        resp = {"available": True, "curves": [
            {"returnPeriod": 2, "points": [
                {"durMin": 10, "intensityMmH": 63.0},
                {"durMin": 720, "intensityMmH": 2.2},   # fuera de la grilla -> se ignora
            ]},
        ]}
        filas = g.filas_estacion(self.est, resp)
        self.assertEqual(len(filas), 1)
        fila = filas[0]
        self.assertEqual(fila["estacion"], "TIBAITATA_-_AUT_21206990")
        self.assertEqual(fila["duracion_min"], 10)
        self.assertEqual(fila["Tr_anios"], 2)
        self.assertEqual(fila["I_plataforma_mmh"], 63.0)
        self.assertAlmostEqual(fila["I_oficial_mmh"], 75.39, delta=0.1)


if __name__ == "__main__":
    unittest.main()

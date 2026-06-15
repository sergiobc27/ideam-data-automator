import unittest

import pandas as pd

from ideam_socrata import physical_ranges as pr


class ExpectedPressureTests(unittest.TestCase):
    def test_nivel_del_mar(self):
        self.assertAlmostEqual(pr.expected_pressure_hpa(0.0), 1013.25, places=1)

    def test_bogota_2600m(self):
        # ~737 hPa por la atmósfera estándar a 2.600 m.
        self.assertTrue(720 < pr.expected_pressure_hpa(2600.0) < 755)

    def test_bounds_sin_altitud_usa_respaldo(self):
        self.assertEqual(pr.pressure_bounds(None), pr._PRESSURE_FALLBACK)
        self.assertEqual(pr.pressure_bounds(float("nan")), pr._PRESSURE_FALLBACK)

    def test_respaldo_no_es_mas_estricto_que_altitud_cero(self):
        """Asimetría (fix): una estación SIN altitud no puede tratarse más
        estricto que una a altitud 0. El techo del respaldo debe ser >= el techo
        ISA+tolerancia a nivel del mar (1013.25 + 80 = 1093.25)."""
        _lo0, hi0 = pr.pressure_bounds(0.0)
        _lo_fb, hi_fb = pr.pressure_bounds(None)
        self.assertGreaterEqual(hi_fb, hi0)

    def test_lectura_alta_a_nivel_del_mar_consistente_con_y_sin_altitud(self):
        """1090 hPa: aceptable a altitud 0 -> también aceptable sin altitud
        (antes se rechazaba sin altitud por el techo 1085, inconsistente)."""
        self.assertIsNone(pr.reject_reason(pr.PRESSURE_ID, 1090.0, altitud=0.0))
        self.assertIsNone(pr.reject_reason(pr.PRESSURE_ID, 1090.0, altitud=None))


class RejectReasonTests(unittest.TestCase):
    def test_none_no_es_rechazo(self):
        self.assertIsNone(pr.reject_reason(pr.PRECIP_ID, None))

    def test_precip_normal_ok(self):
        self.assertIsNone(pr.reject_reason(pr.PRECIP_ID, 12.5))

    def test_precip_negativa_y_centinela_rechazadas(self):
        self.assertIsNotNone(pr.reject_reason(pr.PRECIP_ID, -1.0))
        self.assertIsNotNone(pr.reject_reason(pr.PRECIP_ID, -9999.0))
        self.assertIsNotNone(pr.reject_reason(pr.PRECIP_ID, 9999.0))

    def test_no_finito_rechazado(self):
        self.assertIsNotNone(pr.reject_reason(pr.PRECIP_ID, float("inf")))
        self.assertIsNotNone(pr.reject_reason(pr.PRECIP_ID, float("nan")))

    def test_presion_depende_de_altitud(self):
        # Estación a nivel del mar: 1010 ok, 600 imposible.
        self.assertIsNone(pr.reject_reason(pr.PRESSURE_ID, 1010.0, altitud=5.0))
        self.assertIsNotNone(pr.reject_reason(pr.PRESSURE_ID, 600.0, altitud=5.0))
        # Estación de páramo (~3.000 m): ~700 hPa ok, 1010 imposible.
        self.assertIsNone(pr.reject_reason(pr.PRESSURE_ID, 700.0, altitud=3000.0))
        self.assertIsNotNone(pr.reject_reason(pr.PRESSURE_ID, 1010.0, altitud=3000.0))

    def test_presion_sin_altitud_rango_ancho(self):
        # Sin altitud, 600 hPa cae dentro del respaldo [300,1085].
        self.assertIsNone(pr.reject_reason(pr.PRESSURE_ID, 600.0, altitud=None))
        self.assertIsNotNone(pr.reject_reason(pr.PRESSURE_ID, 50.0, altitud=None))

    def test_nivel_rio_techo(self):
        self.assertIsNone(pr.reject_reason("bdmn-sqnh", 5.9))
        self.assertIsNotNone(pr.reject_reason("bdmn-sqnh", 499.0))

    def test_humedad_y_temp(self):
        self.assertIsNone(pr.reject_reason("uext-mhny", 80.0))
        self.assertIsNotNone(pr.reject_reason("uext-mhny", 120.0))
        self.assertIsNone(pr.reject_reason("ccvq-rp9s", 31.0))
        self.assertIsNotNone(pr.reject_reason("ccvq-rp9s", 80.0))

    def test_dataset_desconocido_no_rechaza(self):
        self.assertIsNone(pr.reject_reason("xxxx-yyyy", 1e6))


class SplitFrameTests(unittest.TestCase):
    def test_split_precip(self):
        frame = pd.DataFrame(
            {
                "source_dataset_id": [pr.PRECIP_ID] * 4,
                "codigoestacion": ["0001", "0001", "0002", "0002"],
                "valorobservado": [10.0, -9999.0, None, 9999.0],
                "unidadmedida": ["mm"] * 4,
            }
        )
        ok, bad = pr.split_frame(frame, pr.PRECIP_ID)
        # Aceptados: el 10.0 y el None (hueco legítimo).
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(bad), 2)
        self.assertIn("motivo", bad.columns)
        self.assertTrue(bad["motivo"].notna().all())

    def test_split_presion_por_altitud(self):
        frame = pd.DataFrame(
            {
                "source_dataset_id": [pr.PRESSURE_ID] * 3,
                "codigoestacion": ["0010", "0020", "0010"],
                "valorobservado": [1010.0, 700.0, 600.0],
                "unidadmedida": ["hPa"] * 3,
            }
        )
        # 0010 a nivel del mar, 0020 a 3.000 m.
        altitudes = {"10": 5.0, "20": 3000.0}
        ok, bad = pr.split_frame(frame, pr.PRESSURE_ID, altitudes)
        # 1010@mar ok, 700@3000m ok, 600@mar imposible.
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(bad), 1)
        self.assertEqual(float(bad["valorobservado"].iloc[0]), 600.0)

    def test_split_dataset_sin_reglas_todo_pasa(self):
        frame = pd.DataFrame(
            {
                "source_dataset_id": ["xxxx-yyyy"] * 2,
                "codigoestacion": ["0001", "0002"],
                "valorobservado": [1e9, -1e9],
            }
        )
        ok, bad = pr.split_frame(frame, "xxxx-yyyy")
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(bad), 0)


if __name__ == "__main__":
    unittest.main()

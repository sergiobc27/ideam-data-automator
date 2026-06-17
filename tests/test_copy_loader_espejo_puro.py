"""Espejo puro (2026-06-17): la ingesta NO filtra por rango físico.

`observaciones` debe ser una copia EXACTA de Socrata. Una lectura físicamente
imposible (p.ej. precip 9999 mm) pero estructuralmente válida ENTRA al espejo tal
cual; solo se desvían a rechazos las filas sin fecha/código/floating_id. La QC
física se movió a la capa de cálculo (vistas/topes de la API)."""

import unittest

import pandas as pd

from ideam_socrata.db import copy_loader as cl


class EspejoPuroTests(unittest.TestCase):
    def _row(self, **over):
        cells = [None] * len(cl.STAGING_COLUMNS)
        cells[cl._COL_INDEX["floating_id_hex"]] = "ab"
        cells[cl._COL_INDEX["codigoestacion"]] = "0001"
        cells[cl._COL_INDEX["fechaobservacion"]] = pd.Timestamp("2024-01-01T00:00:00Z")
        cells[cl._COL_INDEX["valorobservado"]] = 0.5
        for k, v in over.items():
            cells[cl._COL_INDEX[k]] = v
        return tuple(cells)

    def test_lectura_fisicamente_imposible_entra_al_espejo(self):
        # precip 9999 mm es imposible PERO entra al espejo intacto (no se filtra).
        safe, motivo = cl._coerce_row_for_copy(self._row(valorobservado=9999.0))
        self.assertIsNotNone(safe)
        self.assertIsNone(motivo)
        self.assertEqual(safe[cl._COL_INDEX["valorobservado"]], 9999.0)

    def test_negativo_centinela_tambien_entra(self):
        # -9999 (centinela del IDEAM) ya NO se desvía: el espejo lo conserva.
        safe, motivo = cl._coerce_row_for_copy(self._row(valorobservado=-9999.0))
        self.assertIsNotNone(safe)
        self.assertIsNone(motivo)

    def test_fila_sin_fecha_si_se_desvia(self):
        # Único desvío permitido: estructural (violaría NOT NULL).
        safe, motivo = cl._coerce_row_for_copy(self._row(fechaobservacion=None))
        self.assertIsNone(safe)
        self.assertIn("fechaobservacion", motivo)

    def test_no_existe_saneo_fisico_de_ingesta(self):
        # Regresión: el saneo físico de ingesta fue retirado (vive en la capa de
        # cálculo). No debe reaparecer en copy_loader.
        self.assertFalse(hasattr(cl, "_sanitize"))
        self.assertFalse(hasattr(cl, "_record_rejections"))
        self.assertFalse(hasattr(cl, "_altitudes"))


if __name__ == "__main__":
    unittest.main()

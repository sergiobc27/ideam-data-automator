"""Cobertura de validate_payload: el portero que decide qué filas se suben a
Socrata (separa aceptadas/rechazadas según el modelo IdeamObservation).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideam_socrata.validation import IdeamObservation, validate_payload


@unittest.skipIf(IdeamObservation is None, "pydantic no instalado")
class ValidatePayloadTests(unittest.TestCase):
    def _valido(self, **cambios):
        rec = {
            "floating_id": "abc123",
            "source_dataset_id": "s54a-sgyg",
            "codigoestacion": "0021195190",
            "codigosensor": "01",
            "fechaobservacion": "2024-01-01T00:00:00.000",
            "valorobservado": 1.2,
            "latitud": 10.0,
            "longitud": -74.0,
        }
        rec.update(cambios)
        return rec

    def test_registro_valido_aceptado(self):
        aceptados, rechazados = validate_payload([self._valido()])
        self.assertEqual(len(aceptados), 1)
        self.assertEqual(rechazados, [])

    def test_latitud_fuera_de_rango_rechazada(self):
        aceptados, rechazados = validate_payload([self._valido(latitud=999)])
        self.assertEqual(aceptados, [])
        self.assertEqual(len(rechazados), 1)
        self.assertEqual(rechazados[0]["index"], 0)

    def test_longitud_fuera_de_rango_rechazada(self):
        aceptados, rechazados = validate_payload([self._valido(longitud=-500)])
        self.assertEqual(aceptados, [])
        self.assertEqual(len(rechazados), 1)

    def test_campo_requerido_faltante_rechazado(self):
        rec = self._valido()
        del rec["floating_id"]
        aceptados, rechazados = validate_payload([rec])
        self.assertEqual(aceptados, [])
        self.assertEqual(len(rechazados), 1)

    def test_mezcla_valido_e_invalido_se_particiona(self):
        aceptados, rechazados = validate_payload([self._valido(), self._valido(latitud=200)])
        self.assertEqual(len(aceptados), 1)
        self.assertEqual(len(rechazados), 1)
        self.assertEqual(rechazados[0]["index"], 1)


if __name__ == "__main__":
    unittest.main()

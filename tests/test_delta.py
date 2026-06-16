"""TDD del delta incremental: la cláusula incremental debe ser ``>=`` (no ``>``).

El high-water mark se trunca a segundos; con ``>`` estricto, dos observaciones
que comparten el mismo segundo pueden perderse silenciosamente cuando el HWM cae
en una de ellas. El upsert es idempotente (DO UPDATE por floating_id), así que
re-incluir el segundo del HWM con ``>=`` no duplica y no pierde filas.
"""

import unittest
from datetime import datetime

from ideam_socrata.db import delta


class DeltaWhereTests(unittest.TestCase):
    def test_usa_mayor_o_igual_y_escapa_el_literal(self):
        where = delta._delta_where("fechaobservacion", datetime(2020, 1, 2, 3, 4, 5))
        self.assertEqual(where, "fechaobservacion >= '2020-01-02T03:04:05'")


if __name__ == "__main__":
    unittest.main()

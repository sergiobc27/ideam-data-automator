"""Selección de sensor por año en el precómputo IDF (deploy/idf_schema.sql).

El ORDER BY del CTE `dom` decide QUÉ sensor representa cada año en estaciones
multi-sensor. Un cambio de tie-break (o una regresión al refactorizar el schema)
puede reintroducir el bug 0257 (el GPRS sub-reportador que ganaba por tener más
slots y bajaba la lámina, p.ej. Soledad 2024 28,9->10,0 mm/10min). Este test
aplica el SQL REAL del archivo a un esquema temporal y afirma:

  1. Con dos sensores no-0257, gana el MÁS COMPLETO (más slots).
  2. Con 0257 presente, 0257 PIERDE aunque tenga más slots.
  3. Empate en slots -> desempata por lámina (sval DESC), determinista.

Requiere un PostgreSQL real (>=14, por date_bin): se salta si no está la variable
de entorno IDEAM_TEST_DSN. No hay Postgres embebido en esta máquina, así que en
CI/local sin DSN el test simplemente se omite (no falla). Escrito en unittest puro
(sin pytest) porque el job `test` de CI corre `unittest discover` y no instala
pytest ni psycopg; por eso psycopg se importa dentro de setUp, no a nivel módulo.
"""

import os
import unittest
import uuid
from pathlib import Path

_DSN = os.environ.get("IDEAM_TEST_DSN")
_IDF_SQL = Path(__file__).resolve().parents[1] / "deploy" / "idf_schema.sql"
_PRECIP_DS = "s54a-sgyg"


@unittest.skipUnless(
    _DSN, "define IDEAM_TEST_DSN (Postgres >=14) para ejercer el SQL real de IDF"
)
class SeleccionSensorIDF(unittest.TestCase):
    def setUp(self):
        try:
            import psycopg
        except ImportError:
            self.skipTest("psycopg no instalado")
        self._psycopg = psycopg
        self.conn = psycopg.connect(_DSN, autocommit=True)
        self.schema = f"idf_test_{uuid.uuid4().hex[:12]}"
        self.conn.execute(f'CREATE SCHEMA "{self.schema}"')
        self.conn.execute(f'SET search_path TO "{self.schema}"')
        # Tabla mínima con las columnas que consulta idf_schema.sql.
        self.conn.execute(
            "CREATE TABLE observaciones ("
            "  source_dataset_id text,"
            "  codigoestacion    text,"
            "  codigosensor      text,"
            "  fechaobservacion  timestamptz,"
            "  valorobservado    real)"
        )
        # Aplica el ARCHIVO REAL (crea idf_max_anual, idf_estado y la función).
        self.conn.execute(_IDF_SQL.read_text(encoding="utf-8"))

    def tearDown(self):
        conn = getattr(self, "conn", None)
        if conn is not None:
            try:
                conn.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
            finally:
                conn.close()

    def _sembrar(self, codigo, sensores_vals, start="2020-06-01 00:00:00+00"):
        """Inserta, por sensor, una lectura cada 10 min arrancando en `start`."""
        for sensor, vals in sensores_vals.items():
            for i, v in enumerate(vals):
                self.conn.execute(
                    "INSERT INTO observaciones "
                    "(source_dataset_id, codigoestacion, codigosensor, fechaobservacion, valorobservado) "
                    "VALUES (%s, %s, %s, %s::timestamptz + make_interval(mins => %s), %s)",
                    (_PRECIP_DS, codigo, sensor, start, i * 10, v),
                )

    def _max_10min(self, codigo):
        """max_mm de la duración de 10 min = pico de la lectura del sensor ganador."""
        row = self.conn.execute(
            "SELECT max_mm FROM idf_max_anual WHERE codigoestacion = %s AND dur_min = 10",
            (codigo,),
        ).fetchone()
        return row[0] if row else None

    def test_gana_el_sensor_mas_completo(self):
        # 'A' tiene más slots (5) que 'B' (3); ninguno es 0257 -> gana A (su pico 9.0).
        codigo = "ESTMASCOMPLETO"
        self._sembrar(codigo, {
            "0240": [0.1, 0.1, 9.0, 0.1, 0.1],   # 5 slots, pico 9.0
            "0301": [0.1, 4.0, 0.1],             # 3 slots, pico 4.0
        })
        self.conn.execute("SELECT idf_compute_station(%s, 1)", (codigo,))
        self.assertAlmostEqual(self._max_10min(codigo), 9.0, delta=0.05)

    def test_0257_pierde_aunque_tenga_mas_slots(self):
        # 0257 tiene MÁS slots (6) que el medidor real 0240 (3), pero debe PERDER:
        # gana 0240 y su pico 9.0 (con el bug, ganaría 0257 y saldría 3.0).
        codigo = "EST0257"
        self._sembrar(codigo, {
            "0240": [0.1, 9.0, 0.1],                   # 3 slots, pico 9.0 (medidor real)
            "0257": [0.1, 0.1, 3.0, 0.1, 0.1, 0.1],    # 6 slots, pico 3.0 (GPRS)
        })
        self.conn.execute("SELECT idf_compute_station(%s, 1)", (codigo,))
        self.assertAlmostEqual(self._max_10min(codigo), 9.0, delta=0.05)

    def test_empate_en_slots_desempata_por_lamina(self):
        # Mismos slots (4 y 4), ninguno 0257 -> desempata sval DESC: gana 'Y' (mayor
        # lámina), determinista. Su pico 8.0 debe aflorar.
        codigo = "ESTEMPATE"
        self._sembrar(codigo, {
            "0240": [0.1, 0.1, 5.0, 0.1],   # 4 slots, suma ~5.3, pico 5.0
            "0301": [0.1, 0.1, 8.0, 0.1],   # 4 slots, suma ~8.3, pico 8.0  (gana)
        })
        self.conn.execute("SELECT idf_compute_station(%s, 1)", (codigo,))
        self.assertAlmostEqual(self._max_10min(codigo), 8.0, delta=0.05)

    def test_pct_slots_reales_expuesto(self):
        # La columna nueva pct_slots_reales debe poblarse (100% cuando no hay huecos
        # dentro de la ventana del máximo de 10 min: es un único slot real).
        codigo = "ESTPCT"
        self._sembrar(codigo, {"0240": [0.1, 7.0, 0.1, 0.1]})
        self.conn.execute("SELECT idf_compute_station(%s, 1)", (codigo,))
        row = self.conn.execute(
            "SELECT pct_slots_reales FROM idf_max_anual "
            "WHERE codigoestacion = %s AND dur_min = 10",
            (codigo,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 100.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()

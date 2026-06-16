"""Auditoría TZ: la sesión del ingestor NO fijaba el timezone, así que dependía
del default del servidor Postgres.

Verificado EN EL BOX (2026-06-16): el default del servidor es America/Bogota, y
TODO el histórico se ingirió con esa sesión; el pool de la API (api/app/db.py) y
el exporter (to_char) también asumen America/Bogota, de modo que las marcas de
tiempo naive del IDEAM (hora local) hacen round-trip correcto. Por eso la
conexión del ingestor debe fijar timezone=America/Bogota EXPLÍCITO: blinda contra
un cambio del default del servidor SIN alterar el comportamiento. Fijar UTC aquí
sería un error: desplazaría 5h los datos NUEVOS respecto al histórico y al
exporter."""

import unittest

import psycopg

from ideam_socrata.db import connection


class ConnectionTimezoneTests(unittest.TestCase):
    def setUp(self):
        self._real_connect = psycopg.connect
        self.capturado = {}

        def _fake_connect(dsn, **kwargs):
            self.capturado["dsn"] = dsn
            self.capturado["kwargs"] = kwargs
            return object()  # conexión simulada; no tocamos la DB

        psycopg.connect = _fake_connect

    def tearDown(self):
        psycopg.connect = self._real_connect

    def test_get_conn_fija_timezone_bogota_explicito(self):
        import os

        os.environ["DATABASE_URL"] = "postgresql://test@localhost/test"
        connection.get_conn()
        options = self.capturado["kwargs"].get("options", "")
        # America/Bogota (NO UTC): debe coincidir con el default del servidor,
        # el pool de la API y el exporter, para que el histórico y los datos
        # nuevos sean consistentes y el round-trip de hora local sea correcto.
        self.assertIn("timezone=America/Bogota", options)
        self.assertNotIn("timezone=UTC", options)

    def test_get_conn_propaga_autocommit(self):
        import os

        os.environ["DATABASE_URL"] = "postgresql://test@localhost/test"
        connection.get_conn(autocommit=True)
        self.assertTrue(self.capturado["kwargs"].get("autocommit"))


if __name__ == "__main__":
    unittest.main()

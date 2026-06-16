"""Auditoría TZ: la sesión del ingestor NO fijaba el timezone, así que la
consistencia UTC de los caggs (que asumen cubetas a medianoche UTC) dependía del
default del servidor Postgres. Si ese default no es UTC, los timestamps naive de
la ingesta se desplazarían y romperían analytics/preview en silencio.

La conexión del ingestor debe fijar timezone=UTC explícito, igual que el pool de
la API fija el suyo (api/app/db.py)."""

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

    def test_get_conn_fija_timezone_utc(self):
        import os

        os.environ["DATABASE_URL"] = "postgresql://test@localhost/test"
        connection.get_conn()
        options = self.capturado["kwargs"].get("options", "")
        self.assertIn("timezone=UTC", options)

    def test_get_conn_propaga_autocommit(self):
        import os

        os.environ["DATABASE_URL"] = "postgresql://test@localhost/test"
        connection.get_conn(autocommit=True)
        self.assertTrue(self.capturado["kwargs"].get("autocommit"))


if __name__ == "__main__":
    unittest.main()

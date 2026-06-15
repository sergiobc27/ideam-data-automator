"""TDD del aislamiento transaccional de _altitudes (fix CRITICO).

Si el SELECT de altitudes falla, NO debe dejar la transacción del COPY en
estado abortado ni cachear {} como si fuera un fetch exitoso (eso condenaba
TODOS los lotes posteriores de esa conexión). Debe: rollback + permitir reintento.
"""

import unittest

from ideam_socrata.db import copy_loader as cl


class _FakeCursor:
    def __init__(self, rows=None, raise_on_execute=False):
        self._rows = rows or []
        self._raise = raise_on_execute
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if self._raise:
            raise RuntimeError("relation \"estaciones\" does not exist")

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.rollbacks = 0
        self.commits = 0

    def cursor(self):
        return self._cur

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1


class AltitudesIsolationTests(unittest.TestCase):
    def setUp(self):
        cl._ALTITUDES = None  # estado inicial (sin cachear)

    def tearDown(self):
        cl._ALTITUDES = None

    def test_fetch_exitoso_se_cachea(self):
        conn = _FakeConn(_FakeCursor(rows=[("123", 2600.0), ("45", 5.0)]))
        out = cl._altitudes(conn)
        self.assertEqual(out, {"123": 2600.0, "45": 5.0})
        # cacheado: una segunda llamada no vuelve a consultar
        conn2 = _FakeConn(_FakeCursor(raise_on_execute=True))
        self.assertEqual(cl._altitudes(conn2), {"123": 2600.0, "45": 5.0})
        self.assertEqual(conn2.cursor().executed, [])

    def test_fallo_hace_rollback_y_no_envenena_la_transaccion(self):
        conn = _FakeConn(_FakeCursor(raise_on_execute=True))
        out = cl._altitudes(conn)
        # devuelve un dict vacío (saneo usa el respaldo) PERO sin dejar la
        # transacción abortada: hizo rollback.
        self.assertEqual(out, {})
        self.assertEqual(conn.rollbacks, 1)

    def test_fallo_no_cachea_dict_vacio_permite_reintento(self):
        conn_malo = _FakeConn(_FakeCursor(raise_on_execute=True))
        self.assertEqual(cl._altitudes(conn_malo), {})
        # un reintento posterior (DB ya sana) SÍ debe consultar de nuevo.
        conn_bueno = _FakeConn(_FakeCursor(rows=[("7", 100.0)]))
        self.assertEqual(cl._altitudes(conn_bueno), {"7": 100.0})


if __name__ == "__main__":
    unittest.main()

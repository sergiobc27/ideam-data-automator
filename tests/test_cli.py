"""Cobertura del entrypoint público (CLI ideam-socrata): parser, dispatch de
subcomandos, salida limpia ante cancelación (Ctrl+C / EOF) y resiliencia del
comando verify ante fallos de red. Todo sin tocar la red.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideam_socrata import cli


class ParserTests(unittest.TestCase):
    def test_download_parses_required_flags(self):
        args = cli.build_parser().parse_args(
            [
                "download", "--dataset", "s54a-sgyg",
                "--department", "ATLANTICO", "--department", "BOLIVAR",
                "--start-date", "2024-01-01", "--end-date", "2024-02-01",
                "--csv", "--engine", "soda",
            ]
        )
        self.assertEqual(args.command, "download")
        self.assertEqual(args.dataset, "s54a-sgyg")
        self.assertEqual(args.department, ["ATLANTICO", "BOLIVAR"])
        self.assertEqual(args.start_date, "2024-01-01")
        self.assertEqual(args.end_date, "2024-02-01")
        self.assertTrue(args.csv)
        self.assertEqual(args.engine, "soda")

    def test_download_requires_dataset(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(
                ["download", "--department", "ATLANTICO",
                 "--start-date", "2024-01-01", "--end-date", "2024-02-01"]
            )

    def test_invalid_engine_rejected(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(
                ["download", "--dataset", "x", "--department", "ATLANTICO",
                 "--start-date", "2024-01-01", "--end-date", "2024-02-01",
                 "--engine", "turbo"]
            )

    def test_engine_defaults_to_rapido(self):
        args = cli.build_parser().parse_args(
            ["download", "--dataset", "x", "--department", "ATLANTICO",
             "--start-date", "2024-01-01", "--end-date", "2024-02-01"]
        )
        self.assertEqual(args.engine, "rapido")


class DispatchTests(unittest.TestCase):
    def test_download_invokes_batch_with_kwargs(self):
        with mock.patch("ideam_socrata.batch.download") as m:
            code = cli._dispatch(
                ["download", "--dataset", "s54a-sgyg", "--department", "ATLANTICO",
                 "--start-date", "2024-01-01", "--end-date", "2024-02-01", "--csv"]
            )
        self.assertEqual(code, 0)
        m.assert_called_once()
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["dataset_id"], "s54a-sgyg")
        self.assertEqual(kwargs["departments"], ["ATLANTICO"])
        self.assertEqual(kwargs["start_date"], "2024-01-01")
        self.assertEqual(kwargs["end_date"], "2024-02-01")
        self.assertTrue(kwargs["include_csv"])
        self.assertEqual(kwargs["engine"], "rapido")

    def test_datasets_invokes_list(self):
        with mock.patch("ideam_socrata.batch.list_datasets") as m:
            code = cli._dispatch(["datasets"])
        self.assertEqual(code, 0)
        m.assert_called_once()

    def test_no_command_runs_interactive(self):
        with mock.patch("ideam_socrata.cli.interactive_main") as m:
            code = cli._dispatch([])
        self.assertEqual(code, 0)
        m.assert_called_once()


class MainCancellationTests(unittest.TestCase):
    def test_ctrl_c_exits_cleanly(self):
        with mock.patch("ideam_socrata.cli._dispatch", side_effect=KeyboardInterrupt):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main([])
        self.assertEqual(code, 130)
        self.assertIn("Cancelado", buf.getvalue())

    def test_eof_exits_cleanly(self):
        """Ctrl+D / stdin agotado: salida limpia, sin traceback crudo."""
        with mock.patch("ideam_socrata.cli._dispatch", side_effect=EOFError):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main([])
        self.assertEqual(code, 130)
        self.assertIn("Cancelado", buf.getvalue())


class VerifyResilienceTests(unittest.TestCase):
    def test_sample_query_uses_retry_and_builds_query(self):
        """La muestra pasa por intentar() (reintentos/backoff) Y arma bien la
        consulta (select/order/limit) — se deja correr intentar de verdad
        (side_effect=fn()) para probar conducta, no solo que se llamó un mock."""
        captured = {}

        def fake_get(dataset_id, **kw):
            captured["dataset_id"] = dataset_id
            captured.update(kw)
            return [{"x": 1}]

        with mock.patch.object(cli.CLIENT, "get", side_effect=fake_get), \
             mock.patch("ideam_socrata.cli.intentar", side_effect=lambda fn, desc: fn()) as m_int, \
             mock.patch("ideam_socrata.cli.verify_department_coverage", return_value={}):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli._dispatch(["verify", "--dataset-id", "s54a-sgyg", "--limit", "7"])
        self.assertEqual(code, 0)
        m_int.assert_called()
        self.assertEqual(captured["dataset_id"], "s54a-sgyg")
        self.assertEqual(captured["order"], "fechaobservacion")
        self.assertEqual(captured["limit"], 7)
        self.assertIn("fechaobservacion", captured["select"])
        self.assertIn('"x": 1', buf.getvalue())

    def test_definitive_sample_failure_returns_nonzero(self):
        """Un comando de 'verificación' NO debe reportar éxito (exit 0) si la
        muestra falló de verdad. Ejercita el intentar() REAL (CLIENT.get siempre
        falla, sin sleeps): salida limpia (sample_rows null, ok false) PERO
        código != 0 para que un CI no tome el fallo de red como verificación OK."""
        with mock.patch.object(cli.CLIENT, "get", side_effect=RuntimeError("red caida")), \
             mock.patch("ideam_socrata.core.time.sleep", return_value=None), \
             mock.patch("ideam_socrata.cli.verify_department_coverage", return_value={}):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli._dispatch(["verify"])
        self.assertNotEqual(code, 0)
        self.assertIn('"sample_rows": null', buf.getvalue())
        self.assertIn('"ok": false', buf.getvalue())

    def test_empty_sample_is_success(self):
        """Una muestra legítimamente vacía ([]) NO es un fallo: exit 0, ok true."""
        with mock.patch.object(cli.CLIENT, "get", return_value=[]), \
             mock.patch("ideam_socrata.cli.intentar", side_effect=lambda fn, desc: fn()), \
             mock.patch("ideam_socrata.cli.verify_department_coverage", return_value={}):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli._dispatch(["verify"])
        self.assertEqual(code, 0)
        self.assertIn('"ok": true', buf.getvalue())


if __name__ == "__main__":
    unittest.main()

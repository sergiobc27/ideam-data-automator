"""Las exportaciones deben ser ATÓMICAS: si la escritura se corta a la mitad
(Ctrl+C, falta de memoria, caída), NO debe quedar un archivo a medias en la
ruta final que parezca válido. Se escribe a un temporal y se renombra al final.
"""

import sys
import unittest
from pathlib import Path
import tempfile
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideam_socrata.exporting import _atomic_write, export_by_department_municipality


class AtomicWriteTests(unittest.TestCase):
    def test_writes_content_into_place(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out.txt"
            _atomic_write(dest, lambda p: p.write_text("hola", encoding="utf-8"))
            self.assertEqual(dest.read_text(encoding="utf-8"), "hola")

    def test_destination_absent_while_writing(self):
        """El archivo final no debe existir MIENTRAS se escribe: la escritura va
        a un temporal y el destino solo aparece (completo) al renombrar."""
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out.txt"
            visto = {}

            def writer(p):
                visto["destino_existe_durante"] = dest.exists()
                visto["escribio_en_otra_ruta"] = Path(p) != dest
                p.write_text("x", encoding="utf-8")

            _atomic_write(dest, writer)
            self.assertFalse(visto["destino_existe_durante"])
            self.assertTrue(visto["escribio_en_otra_ruta"])

    def test_no_partial_file_on_error(self):
        """Si la escritura falla a la mitad: ni archivo final, ni temporal suelto."""
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out.txt"

            def writer(p):
                p.write_text("a medias", encoding="utf-8")
                raise RuntimeError("interrumpido")

            with self.assertRaises(RuntimeError):
                _atomic_write(dest, writer)
            self.assertFalse(dest.exists())
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_overwrites_existing_destination(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out.txt"
            dest.write_text("viejo", encoding="utf-8")
            _atomic_write(dest, lambda p: p.write_text("nuevo", encoding="utf-8"))
            self.assertEqual(dest.read_text(encoding="utf-8"), "nuevo")


class ExportAtomicityTests(unittest.TestCase):
    def test_parquet_failure_leaves_no_partial(self):
        df = pd.DataFrame(
            {"departamento": ["ATLANTICO"], "municipio": ["BARRANQUILLA"], "valorobservado": [1]}
        )
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("pandas.DataFrame.to_parquet", side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    export_by_department_municipality(
                        df, "Precipitación", base_dir=d, timestamp="1200_010126"
                    )
            self.assertEqual(list(Path(d).rglob("*.parquet")), [])
            self.assertEqual(list(Path(d).rglob("*.tmp")), [])

    def test_csv_split_failure_leaves_no_partial(self):
        """Si la escritura de un CSV (split en varios) falla, no debe quedar
        ningún .csv a medias ni temporal suelto en la carpeta del grupo."""
        df = pd.DataFrame(
            {"departamento": ["ATLANTICO"] * 4, "municipio": ["BARRANQUILLA"] * 4, "valorobservado": [1, 2, 3, 4]}
        )
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("pandas.DataFrame.to_csv", side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    export_by_department_municipality(
                        df, "Precipitación", base_dir=d, include_csv=True,
                        timestamp="1200_010126", max_csv_rows=2,
                    )
            self.assertEqual(list(Path(d).rglob("*.csv")), [])
            self.assertEqual(list(Path(d).rglob("*.tmp")), [])

    def test_successful_export_still_produces_valid_parquet(self):
        df = pd.DataFrame(
            {"departamento": ["ATLANTICO"] * 3, "municipio": ["BARRANQUILLA"] * 3, "valorobservado": [1, 2, 3]}
        )
        with tempfile.TemporaryDirectory() as d:
            outputs = export_by_department_municipality(
                df, "Precipitación", base_dir=d, timestamp="1200_010126"
            )
            ruta = Path(outputs[0]["parquet"])
            self.assertTrue(ruta.exists())
            self.assertEqual(len(pd.read_parquet(ruta)), 3)


if __name__ == "__main__":
    unittest.main()

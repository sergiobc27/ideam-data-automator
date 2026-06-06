import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideam_socrata.exporting import export_by_department_municipality, write_coverage_report
from ideam_socrata.query_validation import build_department_filter
from ideam_socrata.transform import normalize_chunk


class QueryExportHelperTests(unittest.TestCase):
    def test_department_filter_includes_accent_variants(self):
        mapping = {"ATLANTICO": ["ATLANTICO", "ATLÁNTICO"]}

        where, replacements, variants = build_department_filter(["ATLANTICO"], mapping)

        self.assertIn("upper(departamento) IN", where)
        self.assertIn("'ATLANTICO'", where)
        self.assertIn("'ATLÁNTICO'", where)
        self.assertIn("ATLANTICO", variants)
        self.assertEqual(replacements["ATLANTICO"], "ATLANTICO")
        self.assertEqual(replacements["ATLÁNTICO"], "ATLANTICO")

    def test_department_normalization_is_accent_insensitive(self):
        data = [
            {
                "codigoestacion": "1",
                "codigosensor": "2",
                "fechaobservacion": "2024-01-01T00:00:00.000",
                "valorobservado": "1.2",
                "departamento": "Atlántico",
                "municipio": "Barranquilla",
            }
        ]
        replacements = {"ATLANTICO": "ATLANTICO", "ATLÁNTICO": "ATLANTICO"}

        df = normalize_chunk(data, "s54a-sgyg", "fechaobservacion", replacements)

        self.assertEqual(df.loc[0, "departamento"], "ATLANTICO")
        self.assertIn("floating_id", df.columns)

    def test_san_andres_incluye_variantes_reales(self):
        """San Andrés vive bajo nombres tipo 'ARCHIPIÉLAGO DE SAN ANDRES...' en la
        fuente (verificado en vivo 2026-06-06); el filtro debe cubrirlos o el
        departamento devuelve 0 filas."""
        from ideam_socrata.config import MAPEO_DEPARTAMENTOS

        where, replacements, variants = build_department_filter(
            ["SAN ANDRES Y PROVIDENCIA"], MAPEO_DEPARTAMENTOS
        )
        self.assertIn("'ARCHIPIELAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA'", where)
        self.assertIn("'ARCHIPIÉLAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA'", where)
        self.assertIn("'ARCHIPIELAGO DE SAN ANDRES, PROVIDENCIA Y SANTA CATALINA'", where)
        self.assertIn("'SAN ANDRÉS PROVIDENCIA'", where)
        # todas las variantes normalizan al canonico
        self.assertEqual(
            replacements["ARCHIPIELAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA"],
            "SAN ANDRES Y PROVIDENCIA",
        )

    def test_csv_dates_are_excel_friendly(self):
        data = [
            {
                "codigoestacion": "1",
                "codigosensor": "2",
                "fechaobservacion": "2016-12-31T23:50:00.000",
                "valorobservado": "5.4",
                "departamento": "ATLANTICO",
                "municipio": "BARRANQUILLA",
            }
        ]
        df = normalize_chunk(data, "s54a-sgyg", "fechaobservacion")
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["fechaobservacion"]))

        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = export_by_department_municipality(
                df, "Precipitación", base_dir=tmpdir, include_csv=True, timestamp="1200_010126"
            )
            contenido = Path(outputs[0]["csv"][0]).read_text(encoding="utf-8-sig")
            # sin la 'T': Excel lo reconoce como fecha y permite filtrar por año/mes/día
            self.assertIn("2016-12-31 23:50:00", contenido)
            self.assertNotIn("2016-12-31T23:50:00", contenido)

    def test_coverage_report_lists_station_ranges(self):
        df = pd.DataFrame(
            {
                "codigoestacion": ["0021195190"] * 3 + ["0029004520"] * 2,
                "nombreestacion": ["LAS FLORES"] * 3 + ["ESCUELA NAVAL"] * 2,
                "municipio": ["BARRANQUILLA"] * 5,
                "fechaobservacion": pd.to_datetime(
                    ["2016-06-10", "2016-07-01", "2020-01-15", "2019-03-01", "2026-01-01"]
                ),
                "valorobservado": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            ruta = write_coverage_report(
                df,
                "Precipitación",
                tmpdir,
                date_column="fechaobservacion",
                query_info={"Departamentos": "ATLANTICO", "Años solicitados": "2001–2026"},
                duplicates=7,
                timestamp="1200_010126",
            )
            contenido = Path(ruta).read_text(encoding="utf-8")

        self.assertIn("RESUMEN DE DESCARGA — Precipitación", contenido)
        self.assertIn("Departamentos: ATLANTICO", contenido)
        self.assertIn("Filas únicas: 5", contenido)
        self.assertIn("7 duplicados depurados", contenido)
        self.assertIn("Rango real de los datos: 2016-06-10 — 2026-01-01", contenido)
        self.assertIn("0021195190", contenido)
        self.assertIn("2016-06-10 → 2020-01-15", contenido)
        self.assertIn("0029004520", contenido)
        self.assertIn("DHIME", contenido)

    def test_export_organizes_and_splits_csv(self):
        df = pd.DataFrame(
            {
                "departamento": ["ATLANTICO"] * 5,
                "municipio": ["BARRANQUILLA"] * 5,
                "valorobservado": [1, 2, 3, 4, 5],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = export_by_department_municipality(
                df,
                "Precipitación",
                base_dir=tmpdir,
                include_csv=True,
                timestamp="1200_010126",
                max_csv_rows=3,
            )

            self.assertEqual(len(outputs), 1)
            parquet_path = Path(outputs[0]["parquet"])
            csv_paths = [Path(path) for path in outputs[0]["csv"]]

            self.assertTrue(parquet_path.exists())
            self.assertEqual(parquet_path.parent.name, "BARRANQUILLA")
            self.assertEqual(parquet_path.parent.parent.name, "ATLANTICO")
            self.assertEqual(len(csv_paths), 3)
            self.assertTrue(csv_paths[0].name.endswith("1200_010126.csv"))
            self.assertTrue(csv_paths[1].name.endswith("1200_010126_2.csv"))
            self.assertTrue(csv_paths[2].name.endswith("1200_010126_3.csv"))


if __name__ == "__main__":
    unittest.main()

"""La CLI usa 'requests' en sus comandos núcleo (batch.py): debe declararse como
dependencia core, no llegar solo de gancho transitivo por sodapy.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CoreDependenciesTests(unittest.TestCase):
    def test_requests_in_pyproject_core_dependencies(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        # primer bloque 'dependencies = [...]' = dependencias core (no el extra [server])
        m = re.search(r"\ndependencies = \[(.*?)\]", text, re.S)
        self.assertIsNotNone(m, "no se encontró el bloque dependencies en pyproject.toml")
        self.assertIn("requests", m.group(1))

    def test_requests_in_requirements_txt(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^\s*requests")

    def test_requests_not_duplicated_in_server_extra(self):
        """requests es dependencia core: NO debe quedar duplicado en el extra
        [project.optional-dependencies].server (que ya solo lleva psycopg)."""
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r"\nserver = \[(.*?)\]", text, re.S)
        self.assertIsNotNone(m, "no se encontró el extra server en pyproject.toml")
        self.assertNotIn("requests", m.group(1))

    def test_requirements_txt_matches_pyproject_core_dependencies(self):
        """requirements.txt se autodeclara "espejo" de pyproject (ver su
        cabecera): si alguien sube un piso o agrega/quita una dependencia core
        en un archivo y se olvida del otro, este test debe fallar. Antes solo
        se comprobaba 'requests' suelto y una desincronización real (p.ej.
        'requirements.txt no incluía textual', CHANGELOG) pasaba en verde."""
        pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r"\ndependencies = \[(.*?)\]", pyproject_text, re.S)
        self.assertIsNotNone(m, "no se encontró el bloque dependencies en pyproject.toml")
        pyproject_deps = set(re.findall(r'"([A-Za-z0-9_.\-]+>=?[0-9][\w.]*)"', m.group(1)))
        self.assertTrue(pyproject_deps, "no se extrajo ninguna dependencia de pyproject.toml")

        requirements_text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        requirements_deps = {
            line.strip()
            for line in requirements_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        self.assertEqual(
            pyproject_deps,
            requirements_deps,
            "requirements.txt se desincronizó de pyproject.toml (nombre y/o piso "
            "de version); actualiza requirements.txt para que sea un espejo exacto "
            "del bloque 'dependencies' de pyproject.toml.",
        )


if __name__ == "__main__":
    unittest.main()

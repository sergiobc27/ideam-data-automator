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


if __name__ == "__main__":
    unittest.main()

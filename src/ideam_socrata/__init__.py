"""IDEAM Data Automator package."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("ideam-data-automator")
except PackageNotFoundError:  # ejecutado desde el código fuente sin instalar
    __version__ = "0.0.0+local"

"""Hace ejecutable el paquete como módulo: `python -m ideam_socrata tui`.

Es la vía de arranque que funciona aunque la carpeta Scripts de Python no
esté en el PATH (caso común en Windows), donde `ideam-socrata` no se
reconoce como comando.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

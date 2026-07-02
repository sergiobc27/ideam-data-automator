"""Punto de entrada del ejecutable de Windows (PyInstaller).

Doble clic -> abre la interfaz visual (TUI). Si se pasan argumentos por línea de
comandos, se comporta como la CLI normal (datasets, download, interactive,
verify...). Así el mismo .exe sirve de app de doble clic y de CLI.
"""

import sys

if __name__ == "__main__":
    argv = sys.argv[1:]

    # Autodiagnóstico interno (usado para verificar el .exe ya empaquetado):
    # monta la TUI headless y confirma que Textual y el tema cargan, sin abrir
    # la interfaz. No es para el usuario final.
    if argv[:1] == ["--selftest"]:
        import asyncio

        from ideam_socrata.tui import IdeamTUI

        async def _t() -> None:
            app = IdeamTUI()
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.theme == "cuc", app.theme

        asyncio.run(_t())
        print("SELFTEST_OK theme=cuc")
        raise SystemExit(0)

    from ideam_socrata.cli import main

    if not argv:
        argv = ["tui"]  # doble clic: arranca directo en la interfaz visual
    raise SystemExit(main(argv))

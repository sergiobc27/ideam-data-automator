# -*- mode: python ; coding: utf-8 -*-
#
# Comando canonico de build (desde la raiz del repo, con el .venv activo):
#   pyinstaller packaging/IDEAM-Data-Automator.spec --distpath dist_exe --workpath build_exe
#
# Este .spec es la UNICA fuente de verdad del .exe: no pasar --icon ni
# --collect-all por linea de comandos, todo vive aqui para que el build sea
# reproducible desde lo que hay en git.
import os

from PyInstaller.utils.hooks import collect_all

# SPECPATH lo inyecta PyInstaller con el directorio de este .spec (packaging/).
# Se usa para que el icono se resuelva igual sin importar desde donde se invoque
# el comando (p.ej. si algun dia corre desde otro cwd).
ICON_PATH = os.path.join(SPECPATH, 'assets', 'icono.ico')

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('textual')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rich')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ideam_socrata')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['ideam_app.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # La CLI/TUI local solo habla con Socrata (HTTP), nunca con Postgres: el
    # driver psycopg pertenece al extra opcional [server] (espejo/ingesta) y
    # collect_all('ideam_socrata') lo arrastra igual porque sigue el import a
    # nivel de modulo en src/ideam_socrata/db/connection.py. Se excluye a
    # proposito para no cargar ~16MB de binarios nativos muertos en el .exe.
    excludes=['psycopg', 'psycopg_binary', 'psycopg_pool'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='IDEAM-Data-Automator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
)

@echo off
REM Lanzador de IDEAM Data Automator (interfaz visual).
REM Doble clic: se relanza a si mismo en una ventana MAXIMIZADA.
if /i "%~1" neq "max" (
    start "IDEAM Data Automator" /max "%~f0" max
    exit /b
)
title IDEAM Data Automator
set PYTHONUTF8=1

REM 1) Hace falta Python (instalador de python.org con "Add python.exe to PATH").
where python >nul 2>&1
if errorlevel 1 (
    echo No se encontro Python. Instalalo gratis desde python.org/downloads
    echo y marca la casilla "Add python.exe to PATH" durante la instalacion.
    pause
    exit /b 1
)

REM 2) Si la herramienta aun no esta instalada, se instala desde PyPI.
python -m ideam_socrata --version >nul 2>&1
if errorlevel 1 (
    echo Instalando IDEAM Data Automator ^(solo la primera vez^)...
    python -m pip install ideam-data-automator
)

REM 3) Abrir la interfaz visual.
python -m ideam_socrata tui
pause

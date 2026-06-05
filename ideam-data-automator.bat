@echo off
REM Lanzador de IDEAM Data Automator (interfaz visual Textual).
REM Doble clic: se relanza a si mismo en una ventana MAXIMIZADA.
if /i "%~1" neq "max" (
    start "IDEAM Data Automator" /max "%~f0" max
    exit /b
)
title IDEAM Data Automator
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=%~dp0src
".venv\Scripts\python.exe" -m ideam_socrata.cli tui
pause

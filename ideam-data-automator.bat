@echo off
REM Lanzador de IDEAM Data Automator (interfaz visual Textual).
REM Doble clic para abrir el asistente de descarga.
title IDEAM Data Automator
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=%~dp0src
".venv\Scripts\python.exe" -m ideam_socrata.cli tui
pause

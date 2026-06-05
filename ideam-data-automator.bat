@echo off
REM Lanzador del asistente interactivo de IDEAM Data Automator.
REM Doble clic para abrir los menus guiados de descarga.
title IDEAM Data Automator - Asistente
set PYTHONUTF8=1
set PYTHONPATH=%~dp0src
".venv\Scripts\python.exe" -m ideam_socrata.cli interactive
pause

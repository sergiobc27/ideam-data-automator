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
REM Respaldo para consolas que ignoran /max (conhost clasico): maximizar via Win32.
powershell -NoProfile -Command "Add-Type -Name W -Namespace U -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool ShowWindow(System.IntPtr h, int n); [DllImport(\"kernel32.dll\")] public static extern System.IntPtr GetConsoleWindow();'; [U.W]::ShowWindow([U.W]::GetConsoleWindow(), 3)" >nul 2>&1
".venv\Scripts\python.exe" -m ideam_socrata.cli tui
pause

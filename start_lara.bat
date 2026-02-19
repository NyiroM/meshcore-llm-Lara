@echo off
REM LARA Launcher - PowerShell átirányítás
REM A .bat fájlok Ctrl+C kezeléséhez mindig "Terminate batch job?" promptot dobnak.
REM Ezért átirányítjuk a PowerShell launcherhez, ami ezt nem csinálja.

echo.
echo [i] Launching via PowerShell for better Ctrl+C handling...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_lara.ps1"
exit /b %errorlevel%

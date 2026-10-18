@echo off
cd /d "%~dp0"
where pyw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pyw.exe -3 "%~dp0music_collector.pyw"
    exit /b
)
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pythonw.exe "%~dp0music_collector.pyw"
    exit /b
)
where python.exe >nul 2>nul
if not errorlevel 1 (
    python.exe "%~dp0music_collector.pyw"
    exit /b
)
echo Python 3.11 or newer is required. Install it from https://www.python.org/
pause

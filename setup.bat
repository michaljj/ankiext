@echo off
REM AnkiExt one-time setup — run ONCE on each new computer (needs Python 3.10+ and internet the first time).
REM Creates a local .venv\ with the optional packages (keyboard, pystray, pillow) so the app
REM then works offline. After this, just use run.bat.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    echo .venv already exists — use run.bat to start.
    echo (Run "del .venv" first if you want to rebuild it.)
    pause
    exit /b 0
)

echo Creating local Python virtual environment (.venv)...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: could not create .venv. Is Python 3.10+ installed and on your PATH?
    pause
    exit /b 1
)

echo Installing dependencies from requirements.txt...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo WARNING: dependency install had errors. The core app still works with stdlib only
    echo          (hotkey/tray extras may be missing). You can re-run this script later.
    pause
)

echo.
echo Setup complete. Start the app with run.bat
pause
endlocal

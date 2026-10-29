@echo off
REM AnkiExt portable launcher — double-click me on any Windows PC with Python 3.10+.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo Starting AnkiExt (press Ctrl+Shift+D to capture selected text)...
"%PY%" app.py %*
pause
endlocal

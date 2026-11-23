@echo off
setlocal
cd /d "%~dp0"

where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0nes_import_gui.py"
  exit /b
)

where pyw >nul 2>nul
if not errorlevel 1 (
  start "" pyw "%~dp0nes_import_gui.py"
  exit /b
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0nes_import_gui.py"
  pause
  exit /b
)

echo.
echo Python 3 was not found. Install it from https://python.org,
echo then run:  pip install pillow
echo.
pause

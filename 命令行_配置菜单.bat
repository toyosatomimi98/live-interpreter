@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

if not exist ".venv\Scripts\python.exe" (
  echo [Error] venv not found. Run setup first.
  pause
  exit /b 1
)

echo Starting the interactive config menu...
".venv\Scripts\python.exe" menu.py
pause

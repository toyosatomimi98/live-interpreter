@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

if not exist ".venv\Scripts\python.exe" (
  echo [Error] Python virtual environment not found.
  echo Please run the setup steps in README.md first.
  pause
  exit /b 1
)

echo Starting live interpreter. Close the window to stop.
".venv\Scripts\python.exe" tongchuan.py
pause

@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto :run

echo [warn] The Python environment (.venv) was not found.
choice /c yn /n /t 20 /d y /m "      Run the one-time setup now? [Y/n] "
if errorlevel 2 exit /b 1

set LI_SETUP_CHAINED=1
call "%~dp0install.bat"
if not exist "%VENV_PY%" (
  echo [ERROR] Setup did not finish - cannot start yet.
  echo         Run install.bat and fix the errors it reports.
  pause
  exit /b 1
)

:run
echo Starting live-interpreter ...  (close this window to stop)
"%VENV_PY%" tongchuan.py
if errorlevel 1 (
  echo.
  echo [warn] The app exited with an error.
  echo        Run doctor.bat for a health check, or copy this window to the maintainer.
)
pause

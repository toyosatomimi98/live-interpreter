@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [ERROR] .venv not found - run install.bat once, then try again.
  pause
  exit /b 1
)

"%VENV_PY%" "%~dp0tools\make_shortcut.py"
if errorlevel 1 pause
exit /b %ERRORLEVEL%


@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto :build

echo [ERROR] .venv not found - run install.bat once, then build again.
pause
exit /b 1

:build
echo ============================================================
echo   Building the launcher exe (first run downloads PyInstaller)
echo ============================================================
"%VENV_PY%" "%~dp0tools\build_launcher.py"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo [ERROR] Build failed. See the messages above.
  pause
  exit /b %RC%
)
echo Done - the launcher exe is ready in this folder.
pause
exit /b 0


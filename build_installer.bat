@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"

echo ============================================================
echo   Building the Windows installer (needs Inno Setup 6)
echo ============================================================
echo.

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto :build

echo [ERROR] .venv not found - run install.bat once, then build again.
pause
exit /b 1

:build
"%VENV_PY%" "%~dp0tools\build_installer.py"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo [ERROR] Build failed. See the messages above.
  pause
  exit /b %RC%
)
echo Done - the installer is in dist\installer\
pause
exit /b 0


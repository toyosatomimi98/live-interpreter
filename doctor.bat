@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

if exist ".venv\Scripts\python.exe" goto :venv
echo [warn] .venv not found - running the check with the system Python.
echo        (Run install.bat first for a complete check.)
echo.
python doctor.py %*
goto :done

:venv
".venv\Scripts\python.exe" doctor.py %*

:done
echo.
pause

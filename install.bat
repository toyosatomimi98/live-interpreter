@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"

echo ============================================================
echo   live-interpreter - one-time setup (needs internet)
echo ============================================================
echo.

REM ---------- [1/5] find a usable Python (3.10+) ----------
set "PYEXE="
call :probe python
if not defined PYEXE call :probe "py -3"
if not defined PYEXE goto :no_python
echo [1/5] Python found - using: %PYEXE%

set "VENV_PY=%CD%\.venv\Scripts\python.exe"

REM ---------- [2/5] create / reuse the virtual environment ----------
if exist "%VENV_PY%" goto :venv_ok
echo [2/5] Creating virtual environment .venv ...
%PYEXE% -m venv .venv
if not exist "%VENV_PY%" (
  echo [ERROR] Could not create .venv.
  goto :fail
)
goto :venv_done

:venv_ok
"%VENV_PY%" --version >nul 2>&1
if not errorlevel 1 goto :venv_reuse
echo [2/5] Existing .venv cannot run (Python was probably moved or upgraded).
echo       Recreating it now; the folder .venv is regenerated, nothing else is touched.
rmdir /s /q ".venv"
%PYEXE% -m venv .venv
if not exist "%VENV_PY%" (
  echo [ERROR] Could not recreate .venv. Delete the .venv folder by hand and run again.
  goto :fail
)
goto :venv_done

:venv_reuse
echo [2/5] Found existing .venv - refreshing dependencies.

:venv_done
echo.

REM ---------- [3/5] install python packages ----------
echo [3/5] Installing dependencies (a few minutes, ~200 MB) ...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt
if not errorlevel 1 goto :deps_ok
echo [warn] Direct PyPI failed - retrying with a mirror ...
"%VENV_PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if not errorlevel 1 goto :deps_ok
echo.
echo [ERROR] Dependency install failed.
echo         Check your internet / proxy, then run this setup again.
goto :fail

:deps_ok
echo.

REM ---------- [4/5] download speech models ----------
echo [4/5] Downloading speech models (base.en + small.en, about 600 MB) ...
set "MODELS=base.en small.en"
choice /c yn /n /t 25 /d n /m "      Also download large-v3-turbo (1.5 GB, best for offline file mode)? [y/N] "
if errorlevel 2 goto :models_chosen
set "MODELS=base.en small.en large-v3-turbo"
:models_chosen
"%VENV_PY%" setup_models.py %MODELS%
if not errorlevel 1 goto :models_ok
echo [warn] Some models could not be downloaded right now.
echo        The app will try again the first time you use them (needs internet).
:models_ok
echo.

REM ---------- [5/5] verify ----------
echo [5/5] Verifying the installation ...
"%VENV_PY%" doctor.py --quick
echo.
echo ============================================================
echo  Setup finished.
echo    * start now        : double-click  run.bat
echo                         (or the Chinese-named launcher)
echo    * optional API key : double-click  setkey.bat
echo    * health check     : double-click  doctor.bat
echo ============================================================

if defined LI_SETUP_CHAINED goto :done
choice /c yn /n /t 20 /d y /m "Start live-interpreter now? [Y/n] "
if errorlevel 2 goto :done
call "%~dp0run.bat"
goto :done


:no_python
echo [ERROR] Python 3.10 or newer was not found on this PC.
echo.
echo   How to fix:
echo     1. Open  https://www.python.org/downloads/windows/
echo     2. Download the latest "Windows installer (64-bit)" and run it
echo     3. IMPORTANT: tick "Add python.exe to PATH" on the first screen
echo     4. Close this window and run this setup again
echo.
echo   (Tip: after installing Python, double-click  doctor.bat  to confirm.)
echo.
pause
exit /b 1

:fail
echo.
pause
exit /b 1

:done
echo.
pause
exit /b 0


:probe
%~1 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYEXE=%~1"
exit /b 0

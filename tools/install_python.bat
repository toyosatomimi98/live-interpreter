@echo off
REM ---------------------------------------------------------------------------
REM Download + silently install Python 3.12 for the CURRENT USER.
REM
REM * no admin rights needed, no UAC prompt
REM * PATH is deliberately NOT modified - the project only needs the interpreter
REM   once, to create .venv; the launcher always uses .venv afterwards
REM * exits 0 when a usable python.exe is in place, 1 otherwise
REM ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul

set "PY_VER=3.12.10"
set "PY_FILE=python-%PY_VER%-amd64.exe"
set "PY_EXE=%TEMP%\%PY_FILE%"
set "PY_DEST=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PY_URL_MAIN=https://www.python.org/ftp/python/%PY_VER%/%PY_FILE%"
set "PY_URL_MIRROR=https://mirrors.huaweicloud.com/python/%PY_VER%/%PY_FILE%"

if exist "%PY_DEST%" (
  echo [python] already installed: %PY_DEST%
  exit /b 0
)

echo [python] downloading Python %PY_VER% ...
set "OK="
call :try_download "%PY_URL_MAIN%"
if not defined OK call :try_download "%PY_URL_MIRROR%"
if not defined OK call :try_powershell
if not defined OK (
  echo [python] ERROR: could not download the Python installer.
  echo [python]        Check the network/proxy, or install Python by hand from
  echo [python]        https://www.python.org/downloads/windows/  ^(tick
  echo [python]        "Add python.exe to PATH"^) and run this setup again.
  exit /b 1
)

echo [python] installing (current user, no admin, PATH left untouched) ...
"%PY_EXE%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 AssociateFiles=0 Shortcuts=0
echo [python] installer exit code %ERRORLEVEL%

REM the bundle can return before the files are all in place - give it a moment
set /a _tries=0
:wait_loop
if exist "%PY_DEST%" goto :installed
set /a _tries+=1
if %_tries% GEQ 60 goto :scan
timeout /t 2 /nobreak >nul
goto :wait_loop

:scan
for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" 2^>nul') do set "PY_DEST=%%P"
if not exist "%PY_DEST%" (
  echo [python] ERROR: Python was downloaded but the installation did not finish.
  echo [python]        Please install it by hand from https://www.python.org/downloads/windows/
)
if not exist "%PY_DEST%" exit /b 1

:installed
echo [python] ready: %PY_DEST%
exit /b 0


:try_download
echo [python]   %~1
curl.exe -L --fail --silent --show-error -o "%PY_EXE%" %1
if errorlevel 1 exit /b 0
if not exist "%PY_EXE%" exit /b 0
set "OK=1"
exit /b 0

:try_powershell
echo [python]   curl failed, trying PowerShell ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL_MAIN%' -OutFile '%PY_EXE%' } catch { exit 1 }"
if errorlevel 1 exit /b 0
if not exist "%PY_EXE%" exit /b 0
set "OK=1"
exit /b 0

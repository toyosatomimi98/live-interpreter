@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

REM ==== adjustable ====
set "MODEL=large-v3-turbo"
REM COURSE: optional courseware Markdown for glossary/term alignment (empty = off)
set "COURSE="
set "FILE=%~1"

if not exist ".venv\Scripts\python.exe" (
  echo [Error] venv not found. Run setup first.
  pause
  exit /b 1
)

if "%FILE%"=="" (
  for /f "delims=" %%F in ('dir /b /o-d "recordings\*.*" 2^>nul') do (
    set "FILE=recordings\%%F"
    goto :pick
  )
)
:pick
if "%FILE%"=="" (
  echo [Error] No input file and recordings\ is empty.
  echo   Usage: filemode.bat "path\to\audio.mp3"
  echo   Or drop a .wav/.mp3 into recordings\ and run it with no argument.
  pause
  exit /b 1
)
if not exist "%FILE%" (
  echo [Error] File not found: %FILE%
  pause
  exit /b 1
)

echo =====================================================
echo   File mode (offline)   model: %MODEL%
echo   Input : %FILE%
echo   Output: transcripts\ (with --save) + console EN/ZH
if not "%COURSE%"=="" echo   Course: %COURSE%
echo =====================================================
if not "%COURSE%"=="" (
  ".venv\Scripts\python.exe" tongchuan.py --file "%FILE%" --save --model %MODEL% --course "%COURSE%"
) else (
  ".venv\Scripts\python.exe" tongchuan.py --file "%FILE%" --save --model %MODEL%
)
pause

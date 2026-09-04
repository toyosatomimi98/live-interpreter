@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

REM ==== tunable (defaults match argparse) ====
set "MODEL=small.en"
set "MAXSEG=4.0"
set "MINSILENCE=0.5"
set "MINWORDS=3"
REM =========================================

if not exist ".venv\Scripts\python.exe" (
  echo [Error] venv not found. Run the setup step first.
  pause
  exit /b 1
)

echo =====================================================
echo   Microphone live  model: %MODEL%
echo   max_seg=%MAXSEG%s  min_silence=%MINSILENCE%s  min_words=%MINWORDS%
echo   Also SAVES audio to recordings\ (--save-audio)
echo   Press Ctrl+C to stop.
echo =====================================================
REM auto-send a carriage-return to skip the "press Enter" wait
echo. | ".venv\Scripts\python.exe" tongchuan.py --console --source mic --model %MODEL% --max-seg %MAXSEG% --min-silence %MINSILENCE% --min-words %MINWORDS% --save-audio
pause

@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

REM ==== adjustable ====
REM MODEL: tiny.en = fastest for live class capture | base.en = more accurate
set "MODEL=tiny.en"

if not exist ".venv\Scripts\python.exe" (
  echo [Error] venv not found. Run setup first.
  pause
  exit /b 1
)

echo =====================================================
echo   Record system sound  -^> recordings\*.wav   model: %MODEL%
echo   Live captions while saving audio (--save-audio)
echo   Start the lecture/audio, then Press Ctrl+C to stop.
echo   After that, run the file-mode script with no argument to
echo   auto-pick the newest recording.
echo =====================================================
REM auto-send Enter to skip the "press Enter" wait, and save the audio
echo. | ".venv\Scripts\python.exe" tongchuan.py --console --source system --model %MODEL% --save-audio --no-voice
pause

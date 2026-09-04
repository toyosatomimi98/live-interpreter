@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

REM ==== adjustable ====
REM SOURCE: system = system sound (loopback, no mic needed) | mic = microphone
set "SOURCE=system"
REM MODEL: base.en | small.en | medium.en | large-v3-turbo | large-v3
set "MODEL=base.en"
set "MAXSEG=4.0"
set "MINSILENCE=0.5"
set "MINWORDS=3"
REM VOICE: --no-voice (avoid echo on loopback) | --voice (spoken Chinese, ok for mic)
set "VOICE=--no-voice"
REM =========================

if not exist ".venv\Scripts\python.exe" (
  echo [Error] venv not found. Run setup first.
  pause
  exit /b 1
)

if not "%SOURCE%"=="system" if not "%SOURCE%"=="mic" (
  echo [Error] SOURCE must be "system" or "mic".
  pause
  exit /b 1
)

echo =====================================================
echo   Live  source=%SOURCE%  model=%MODEL%
echo   max_seg=%MAXSEG%s  min_silence=%MINSILENCE%s  min_words=%MINWORDS%
echo   Also SAVES audio to recordings\ (--save-audio)
echo   Press Ctrl+C to stop.
echo =====================================================
REM auto-send Enter to skip the "press Enter" wait
echo. | ".venv\Scripts\python.exe" tongchuan.py --console --source %SOURCE% --model %MODEL% --max-seg %MAXSEG% --min-silence %MINSILENCE% --min-words %MINWORDS% --save-audio %VOICE%
pause

@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"

echo [1/3] Creating virtual environment...
python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo [Error] Failed to create venv. Install Python 3.10+ and retry.
  pause
  exit /b 1
)

echo [2/3] Installing dependencies (needs internet)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [Error] Dependency install failed. Check internet and retry.
  pause
  exit /b 1
)

echo [3/3] Downloading whisper model (small.en)...
".venv\Scripts\python.exe" -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8'); print('model ready')"

echo.
echo Done. Double-click "启动同声传译.bat" to run.
pause

@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Optional: add a DeepSeek API key
echo ============================================================
echo   With a key, translation uses DeepSeek (best for technical lectures).
echo   Without a key, the app falls back to the free Google translator.
echo.
echo   Get a key from: https://platform.deepseek.com/api_keys
echo.

if exist ".env" (
  echo Current .env:
  type ".env"
  echo.
)

set "KEY="
set /p KEY="Paste the key (sk-...) then press Enter (blank = cancel): "
if "%KEY%"=="" goto :cancel

> ".env" echo DEEPSEEK_API_KEY=%KEY%
echo.
echo Saved to .env:
type ".env"
echo.
echo (This file stays on this PC only and is never uploaded or committed.)
pause
exit /b 0

:cancel
echo Nothing entered - .env left unchanged.
pause
exit /b 1

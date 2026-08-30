@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set PYTHONPATH=%CD%

REM ===== 可调参数（默认与 argparse 一致，按需修改）=====
set "MODEL=base.en"
set "MAXSEG=4.0"
set "MINSILENCE=0.5"
set "MINWORDS=3"
REM ==============================================

if not exist ".venv\Scripts\python.exe" (
  echo [Error] 未找到虚拟环境，请先双击 安装同声传译.bat
  pause
  exit /b 1
)

echo =====================================================
echo   系统声音内录 实时识别+翻译   模型: %MODEL%
echo   分段上限:%MAXSEG%s  静音判据:%MINSILENCE%s  最少词数:%MINWORDS%
echo   会自动跳过"按 Enter 开始采集"。按 Ctrl+C 结束。
echo =====================================================
REM 送入一个回车，跳过开头的等待
echo. | ".venv\Scripts\python.exe" tongchuan.py --console --source system --model %MODEL% --max-seg %MAXSEG% --min-silence %MINSILENCE% --min-words %MINWORDS% --no-voice
pause

@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Ameba 尺碼量測網站

if exist ".venv-yolo-new\Scripts\python.exe" (
  ".venv-yolo-new\Scripts\python.exe" -u web_dashboard.py --port 8000
) else (
  py -3.12 -u web_dashboard.py --port 8000
)

echo.
echo 網站已停止。請查看上方錯誤訊息。
pause

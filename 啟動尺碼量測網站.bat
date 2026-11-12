@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Ameba 尺碼量測網站

echo.
echo 正在啟動尺碼量測網站，請保持這個視窗開啟...
echo 網站網址：http://127.0.0.1:8000
echo.

if exist ".venv-yolo-new\Scripts\python.exe" (
  ".venv-yolo-new\Scripts\python.exe" -u web_dashboard.py --port 8000 1>dashboard_startup.log 2>&1
) else (
  py -3.12 -u web_dashboard.py --port 8000 1>dashboard_startup.log 2>&1
)

echo.
echo 網站已停止。請查看上方錯誤訊息。
echo 詳細紀錄：%~dp0dashboard_startup.log
type dashboard_startup.log
pause

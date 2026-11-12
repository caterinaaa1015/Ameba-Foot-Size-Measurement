@echo off
setlocal
cd /d "%~dp0"
title Ameba Foot Size Dashboard
echo.
echo Starting dashboard. Keep this window open.
echo Starting LAN sharing mode. Copy the 192.168.x.x address shown below.
echo.

if exist "%~dp0.venv-yolo-new\Scripts\python.exe" (
  "%~dp0.venv-yolo-new\Scripts\python.exe" -u "%~dp0web_dashboard.py" --host 0.0.0.0 --port 8000
) else (
  py -3.12 -u "%~dp0web_dashboard.py" --host 0.0.0.0 --port 8000
)

echo.
echo Dashboard stopped. Read the error above.
pause

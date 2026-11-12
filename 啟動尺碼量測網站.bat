@echo off
setlocal
cd /d "%~dp0"
title Ameba Foot Size Dashboard
echo.
echo Starting dashboard. Keep this window open.
echo Open in browser: http://127.0.0.1:8000
echo.

if exist "%~dp0.venv-yolo-new\Scripts\python.exe" (
  "%~dp0.venv-yolo-new\Scripts\python.exe" -u "%~dp0web_dashboard.py" --port 8000
) else (
  py -3.12 -u "%~dp0web_dashboard.py" --port 8000
)

echo.
echo Dashboard stopped. Read the error above.
pause

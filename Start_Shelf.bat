@echo off
setlocal EnableExtensions
REM Starts ONLY the Clip Shelf (tiny always-on-top window). Needs Start.bat to have been run once.
cd /d "%~dp0"
title Clip Shelf - Console / Live Log
chcp 65001 >nul
set "PYTHONUTF8=1"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Run Start.bat once first - it creates the environment.
    pause
    exit /b 1
)
echo [%date% %time%] Starting the Clip Shelf ...
".venv\Scripts\python.exe" "core\shelf_app.py" %*
if errorlevel 1 (
    echo.
    echo Something went wrong - see logs\shelf_app\sessions\ ^(newest file^). This window stays open.
    pause
)

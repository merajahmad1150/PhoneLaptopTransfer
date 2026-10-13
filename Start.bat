@echo off
setlocal EnableExtensions
REM ====================================================================
REM  Phone-Laptop Transfer - launcher (double-click this file)
REM  * sets the console title      * keeps EVERYTHING on this drive (not C:)
REM  * creates .venv with uv       * installs/updates packages automatically
REM  * never closes by itself when something goes wrong (it waits for a key)
REM ====================================================================
cd /d "%~dp0"
title Phone-Laptop Transfer - Console / Live Log (do not close while using the tool)
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "UV_CACHE_DIR=%~dp0.uv\cache"
set "UV_PYTHON_INSTALL_DIR=%~dp0.uv\python"
set "UV_LINK_MODE=copy"
if not exist "%~dp0temp" mkdir "%~dp0temp"

echo [%date% %time%] Starting Phone-Laptop Transfer
echo [%date% %time%] Folder: %~dp0

where uv >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] "uv" was not found on PATH. Install it from https://docs.astral.sh/uv/ and run this file again.
    goto :fail
)

if not exist ".venv\Scripts\python.exe" (
    echo [%date% %time%] First run: creating the virtual environment with uv ^(Python 3.12^) ...
    uv venv --python 3.12 .venv
    if errorlevel 1 ( echo [ERROR] uv could not create the virtual environment. & goto :fail )
)

echo [%date% %time%] Checking packages ^(fast when everything is already installed^) ...
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 ( echo [ERROR] Installing packages failed - check your internet connection and run again. & goto :fail )

echo [%date% %time%] Launching ...
echo.
".venv\Scripts\python.exe" "core\run.py" %*
set "EXITCODE=%errorlevel%"
echo.
echo [%date% %time%] The tool has closed ^(exit code %EXITCODE%^).
if not "%EXITCODE%"=="0" goto :fail
exit /b 0

:fail
echo.
echo ====================================================================
echo  Something went wrong. The newest file in  logs\sessions\  has every detail.
echo  Please send me that file. This window stays open so you can read it.
echo ====================================================================
pause
exit /b 1

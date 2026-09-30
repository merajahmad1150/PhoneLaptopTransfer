@echo off
REM ============================================================
REM  Phone <-> Laptop Transfer - Launcher
REM  Double-click this file to start the app.
REM ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [ERROR] Virtual environment not found at .venv\
    echo Run these commands once first, from this folder:
    echo.
    echo     uv venv
    echo     .venv\Scripts\activate
    echo     uv pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Starting Phone ^<-^> Laptop Transfer...
echo (Closing this window will also close the app.)
echo.

".venv\Scripts\python.exe" "core\run.py"

if errorlevel 1 (
    echo.
    echo [ERROR] The app exited with an error. See core\logs above,
    echo or check the log file mentioned in the messages above.
    pause
)

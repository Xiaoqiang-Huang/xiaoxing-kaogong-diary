@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Xiaoxing Diary - one click setup and run
echo ==========================================

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Please install Python 3.11+ first:
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Creating .env from .env.example...
    copy ".env.example" ".env" >nul
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$key='dev-' + [guid]::NewGuid().ToString('N'); (Get-Content '.env') -replace '^SECRET_KEY=.*$', ('SECRET_KEY=' + $key) | Set-Content '.env' -Encoding UTF8"
)

echo.
echo Starting server...
echo Open http://127.0.0.1:5000 in your browser.
echo Register an account on /register for first use.
echo.
python start.py

pause

@echo off
cd /d "%~dp0"
title Timestamp Video Clipper

:: If venv exists, just use it directly
if exist "venv\Scripts\python.exe" (
    call venv\Scripts\activate.bat
    python frontend.py
    pause
    exit /b 0
)

:: Otherwise create venv first
echo [SETUP] Creating virtual environment...
py -m venv venv 2>nul || python -m venv venv 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+ and try again.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
pip install -r requirements.txt -q
python frontend.py
pause

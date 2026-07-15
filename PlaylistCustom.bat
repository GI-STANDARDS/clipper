@echo off
cd /d "%~dp0"
title Custom Playlist Download

if exist "venv\Scripts\python.exe" (
    call venv\Scripts\activate.bat
) else (
    echo [SETUP] Creating virtual environment...
    py -m venv venv 2>nul || python -m venv venv 2>nul
    call venv\Scripts\activate.bat
    pip install -r requirements.txt -q
)

python playlist_custom.py
pause

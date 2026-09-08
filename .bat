@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo venv not found - run setup.bat first.
    pause
    exit /b 1
)
call "venv\Scripts\activate.bat"
python bot.py
pause

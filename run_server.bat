@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo venv not found - run setup.bat first.
    pause
    exit /b 1
)
call "venv\Scripts\activate.bat"
echo.
echo ============================================
echo   Bingo Arena - local server (Flask)
echo   Opening: http://localhost:5000
echo   Keep this window open!
echo ============================================
echo.
python migrate_db.py
echo.
python server.py
pause

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
echo   Bingo Arena - HTTPS tunnel
echo   cloudflared gives your local server a
echo   public https:// URL for the Mini App button.
echo   Keep this window open while playing!
echo ============================================
echo.
python tunnel.py
pause

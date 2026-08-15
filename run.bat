@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo venv not found - run setup.bat first.
    pause
    exit /b 1
)
echo Starting Bingo Royale...
echo   [1/2] Local server (Mini App + game loop)  http://localhost:5000
echo   [2/2] Telegram bot
echo.
start "Bingo Server" cmd /k run_server.bat
timeout /t 3 /nobreak >nul
start "Bingo Bot" cmd /k run_bot.bat
exit

@echo off
cd /d "%~dp0\frontend"
echo Building the Mini App (needs Node.js installed)...
where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm not found. Install Node.js from https://nodejs.org and retry.
    pause
    exit /b 1
)
call npm install
call npm run build
echo.
echo Build finished - frontend/dist created. The Flask server serves it at http://localhost:5000
pause

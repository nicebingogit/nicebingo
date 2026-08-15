@echo off
cd /d "%~dp0"
echo ============================================
echo   Bingo Arena - full launch
echo   [1/3] Flask server      localhost:5000
echo   [2/3] HTTPS tunnel      cloudflared
echo   [3/3] Telegram bot      waits for the tunnel URL
echo   Tip: close old Bingo windows first (stop_all.bat)
echo ============================================
echo.
del tunnel_url.txt >nul 2>&1
start "Bingo Server" cmd /k run_server.bat
timeout /t 3 /nobreak >nul
start "Bingo Tunnel" cmd /k run_tunnel.bat
echo Waiting for the HTTPS tunnel URL (up to 60s)...
set /a tries=0
:waiturl
timeout /t 2 /nobreak >nul
if exist tunnel_url.txt goto urlok
set /a tries+=1
if %tries% geq 30 (
    echo Could not detect the tunnel URL - check the Tunnel window.
    pause
    exit /b 1
)
goto waiturl
:urlok
echo Tunnel is up - starting the Telegram bot with the new URL...
start "Bingo Bot" cmd /k run_bot.bat
echo.
echo All three windows are running. In Telegram: /play
exit

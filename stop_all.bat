@echo off
echo Stopping Bingo windows...
taskkill /F /FI "WINDOWTITLE eq Bingo Server*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Bingo Tunnel*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Bingo Bot*" >nul 2>&1
taskkill /F /IM cloudflared.exe >nul 2>&1
echo Done. If any Bingo window is still open, close it manually.
pause

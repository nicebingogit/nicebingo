@echo off
cd /d "%~dp0"
if exist "tools\cloudflared.exe" (
    echo cloudflared is already downloaded (tools\cloudflared.exe).
    echo You can now run run_tunnel.bat.
    pause
    exit /b 0
)
if not exist "tools" mkdir tools
echo.
echo Downloading cloudflared - Cloudflare's free tunnel client, about 50 MB.
echo One-time download. It gives your local server a public https:// address
echo so Telegram will open the Mini App button.
echo.
set "URL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%URL%' -OutFile 'tools\cloudflared.exe' -UseBasicParsing } catch { Write-Host 'PowerShell failed, trying curl...'; curl.exe -L -o 'tools\cloudflared.exe' '%URL%' }"
echo.
if not exist "tools\cloudflared.exe" goto dlfailed
for %%A in ("tools\cloudflared.exe") do if %%~zA LSS 10000000 goto corrupt
echo OK! cloudflared downloaded (about 54 MB).
echo Next: double-click run_tunnel.bat
pause
exit /b 0
:corrupt
echo The downloaded file looks too small - deleting it. Please run this again.
del "tools\cloudflared.exe"
pause
exit /b 1
:dlfailed
echo Download failed - check your internet connection, then run this again.
echo Or download cloudflared-windows-amd64.exe manually and put it in tools\.
pause
exit /b 1

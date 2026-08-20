@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   Nice Bingo - one-time setup
echo ============================================
echo.

where python >nul 2>&1
if %errorlevel%==0 (
    set "PYCMD=python"
) else (
    set "PYCMD=py -3.12"
)
%PYCMD% --version >nul 2>&1
if errorlevel 1 (
    set "PYCMD=py -3.11"
)

echo [1/4] Preparing virtual environment...
if exist "venv\Scripts\python.exe" (
    echo       Using existing venv
) else (
    %PYCMD% -m venv venv
    if errorlevel 1 (
        echo ERROR: could not create the venv. Install Python 3.11 from python.org
        echo        and tick "Add python.exe to PATH", then rerun this file.
        pause
        exit /b 1
    )
)

echo [2/4] Installing pip into the venv...
"venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1
if errorlevel 1 (
    echo       ensurepip failed - trying get-pip.py...
    "venv\Scripts\python.exe" get-pip.py
)

echo [3/4] Installing dependencies (this downloads ~30 MB once)...
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: dependency install failed. Check your internet connection.
    pause
    exit /b 1
)

echo [4/4] Creating .env from template...
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo       Created .env  -  open it and paste your BOT_TOKEN and ADMIN_IDS!
) else (
    echo       .env already exists - leaving it untouched
)

echo.
echo ============================================
echo   Setup finished!
echo   1) open the ".env" file in a text editor
echo   2) paste your BOT_TOKEN and ADMIN_IDS
echo   3) double-click run.bat to start the bot
echo ============================================
pause

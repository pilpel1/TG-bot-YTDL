@echo off
title Bot with Local Server Manager
echo ========================================
echo  Bot with Local Server Manager
echo ========================================
echo.

REM Get current directory for WSL path
set "CURRENT_DIR=%cd%"
set "WSL_PATH=/mnt/c%CURRENT_DIR:~2%"
set "WSL_PATH=%WSL_PATH:\=/%"

echo [1/4] Starting Local Bot API Server...
echo Starting in background window...
start "Local Bot API Server" cmd /k ".\start_local_api.bat"

echo [2/4] Waiting 20 seconds for server to initialize...
timeout /t 20 /nobreak >nul

echo [3/4] Checking server status...
curl -s http://localhost:8081 >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ Local server is responding!
) else (
    echo ⚠ Warning: Server might not be ready yet
)

echo [4/4] Starting bot in WSL2...
echo Opening WSL2 terminal...
echo.
echo WSL Commands that will run:
echo   cd %WSL_PATH%
echo   source venv_wsl/bin/activate
echo   python bot.py
echo.

REM Start WSL in a new window and navigate to project directory
start "Bot WSL Terminal" wsl -d Ubuntu --cd "%WSL_PATH%" bash -c "echo 'Activating virtual environment...'; source venv_wsl/bin/activate; echo 'Starting bot...'; python bot.py; echo 'Bot stopped. Press any key to close.'; read"

echo ========================================
echo  🚀 Bot with Local Server Started!
echo ========================================
echo.
echo Two windows should now be open:
echo  1. Local Bot API Server (background)
echo  2. Bot running in WSL2
echo.
echo To stop everything:
echo  - Close the WSL2 terminal (Ctrl+C then close)
echo  - Run: .\stop_local_api.bat
echo.
echo Press any key to continue...
pause >nul

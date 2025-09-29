@echo off
title Bot with Local Server Manager
echo ========================================
echo  Bot with Local Server Manager
echo ========================================
echo.

REM Get project root directory (go up from scripts\windows)
set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"
set "CURRENT_DIR=%cd%"
set "WSL_PATH=/mnt/c%CURRENT_DIR:~2%"
set "WSL_PATH=%WSL_PATH:\=/%"

echo [1/4] Starting Local Bot API Server...
echo Starting server...
start "Local Bot API Server" cmd /c "scripts\windows\start_local_api.bat"

echo [2/4] Waiting 25 seconds for server to initialize...
timeout /t 25 /nobreak >nul

echo [3/4] Checking server status...
curl -s http://localhost:8081 >nul 2>&1
if %errorlevel% equ 0 (
    echo Local server is responding!
) else (
    echo Warning: Server might not be ready yet
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
echo  Bot with Local Server Started!
echo ========================================
echo.
echo Bot is now running in WSL2 terminal.
echo Local API Server is running in background.
echo.
echo To stop everything:
echo  - Close the WSL2 terminal (Ctrl+C then close)
echo  - Run: scripts\windows\stop_local_api.bat
echo.
echo This window will minimize automatically in 3 seconds...
timeout /t 3 /nobreak >nul

REM Minimize this window
powershell -command "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class Win32 { [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); [DllImport(\"kernel32.dll\")] public static extern IntPtr GetConsoleWindow(); }'; $hwnd = [Win32]::GetConsoleWindow(); [Win32]::ShowWindow($hwnd, 2)" >nul 2>&1

@echo off
title Bot 2GB Launcher
echo ========================================
echo  Bot 2GB Launcher
echo ========================================
echo.

REM Get project root directory (go up from scripts\windows)
set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"
set "CURRENT_DIR=%cd%"
set "WSL_PATH=/mnt/c%CURRENT_DIR:~2%"
set "WSL_PATH=%WSL_PATH:\=/%"

echo [1/2] Opening WSL2 terminal...
echo The advanced 2GB flow now runs entirely inside WSL.
echo This avoids Windows/WSL timing issues when detecting the Local API Server.
echo.
echo WSL Commands that will run:
echo   cd %WSL_PATH%
echo   bash ./scripts/linux/run_bot_advanced_2GB.sh
echo.

REM Start the full advanced flow inside one WSL shell
start "Bot WSL Terminal" wsl -d Ubuntu --cd "%WSL_PATH%" bash -lc "bash ./scripts/linux/run_bot_advanced_2GB.sh; echo; echo 'Flow stopped. Press any key to close.'; read"

echo ========================================
echo  WSL Advanced Flow Started
echo ========================================
echo.
echo The WSL2 terminal is handling both:
echo  - Local Bot API Server startup
echo  - Bot startup with 2GB/50MB fallback
echo.
echo To stop everything:
echo  - Stop the bot in the WSL terminal (Ctrl+C)
echo  - Then run: scripts\windows\stop_local_api.bat
echo.
echo This window will minimize automatically in 3 seconds...
timeout /t 3 /nobreak >nul

REM Minimize this window
powershell -command "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class Win32 { [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); [DllImport(\"kernel32.dll\")] public static extern IntPtr GetConsoleWindow(); }'; $hwnd = [Win32]::GetConsoleWindow(); [Win32]::ShowWindow($hwnd, 2)" >nul 2>&1

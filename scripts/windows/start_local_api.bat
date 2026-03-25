@echo off
echo Starting Telegram Local Bot API Server...
echo.

REM Get project root directory (go up from scripts\windows)
set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"

REM Load API credentials from .env file
for /f "tokens=1,* delims==" %%a in ('type .env ^| findstr /b "TELEGRAM_API_ID="') do set TELEGRAM_API_ID=%%b
for /f "tokens=1,* delims==" %%a in ('type .env ^| findstr /b "TELEGRAM_API_HASH="') do set TELEGRAM_API_HASH=%%b

REM Check if credentials were loaded
if "%TELEGRAM_API_ID%"=="" (
    echo ERROR: TELEGRAM_API_ID not found in .env file
    pause
    exit /b 1
)
if "%TELEGRAM_API_HASH%"=="" (
    echo ERROR: TELEGRAM_API_HASH not found in .env file
    pause
    exit /b 1
)

REM Stop and remove existing container if it exists
wsl docker rm -f telegram-bot-api 2>nul

REM Start new container with your API credentials in WSL2
wsl docker run -d --name telegram-bot-api -p 0.0.0.0:8081:8081 -e TELEGRAM_API_ID=%TELEGRAM_API_ID% -e TELEGRAM_API_HASH=%TELEGRAM_API_HASH% aiogram/telegram-bot-api:latest --local

if %errorlevel% equ 0 (
    echo.
    echo Local Bot API Server started successfully!
    echo Server is running on http://localhost:8081
    echo.
    echo Checking server status...
    timeout /t 3 /nobreak >nul
    wsl docker ps --filter "name=telegram-bot-api"
    echo.
    echo Server started successfully!
    echo This window will minimize in 3 seconds...
    echo Keep this window open - closing it will stop the server.
    timeout /t 3 /nobreak >nul
    
    REM Minimize this window after successful start
    powershell -command "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class Win32 { [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); [DllImport(\"kernel32.dll\")] public static extern IntPtr GetConsoleWindow(); }'; $hwnd = [Win32]::GetConsoleWindow(); [Win32]::ShowWindow($hwnd, 2)" >nul 2>&1
    
    echo Press any key to stop the server...
    pause >nul
) else (
    echo.
    echo Failed to start Local Bot API Server
    echo Check if Docker is running in WSL2
    echo Press any key to exit...
    pause >nul
)

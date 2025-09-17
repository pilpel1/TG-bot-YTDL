@echo off
echo Starting Telegram Local Bot API Server...
echo.

REM TODO: Replace with your actual API credentials from .env
set TELEGRAM_API_ID=your_new_api_id_here
set TELEGRAM_API_HASH=your_new_api_hash_here

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
    echo You can now run your bot with the local API server!
    echo Press any key to continue...
    pause >nul
) else (
    echo.
    echo Failed to start Local Bot API Server
    echo Check if Docker is running in WSL2
    echo Press any key to exit...
    pause >nul
)

@echo off
echo Stopping Telegram Local Bot API Server...
echo.

REM Stop and remove the container in WSL2
wsl docker rm -f telegram-bot-api

if %errorlevel% equ 0 (
    echo Local Bot API Server stopped successfully!
) else (
    echo Failed to stop server or server was not running
)

echo.
echo Press any key to exit...
pause >nul

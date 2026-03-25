@echo off
echo Checking Telegram Local Bot API Server status...
echo.

REM Get project root directory (go up from scripts\windows)
set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"

echo Docker containers:
wsl docker ps --filter "name=telegram-bot-api"
echo.

echo Testing Local API with getMe:
for /f "tokens=1,* delims==" %%a in ('type .env ^| findstr /b "BOT_TOKEN="') do set BOT_TOKEN=%%b
if "%BOT_TOKEN%"=="" (
    echo BOT_TOKEN not found in .env
) else (
    curl -s --max-time 10 "http://localhost:8081/bot%BOT_TOKEN%/getMe" | findstr "\"ok\":true" >nul && echo Local API is ready for bot requests! || echo Local API is not ready for bot requests
)

echo.
echo Logs (last 10 lines):
wsl docker logs --tail 10 telegram-bot-api 2>nul || echo "No logs available or container not running"

echo.
echo Press any key to exit...
pause >nul

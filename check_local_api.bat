@echo off
echo Checking Telegram Local Bot API Server status...
echo.

echo Docker containers:
wsl docker ps --filter "name=telegram-bot-api"
echo.

echo Testing server response:
curl -s http://localhost:8081 && echo. && echo Server is responding! || echo Server is not responding

echo.
echo Logs (last 10 lines):
wsl docker logs --tail 10 telegram-bot-api 2>nul || echo "No logs available or container not running"

echo.
echo Press any key to exit...
pause >nul

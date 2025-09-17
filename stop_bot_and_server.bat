@echo off
title Stop Bot and Local Server
echo ========================================
echo  Stopping Bot and Local Server
echo ========================================
echo.

echo [1/2] Stopping Local Bot API Server...
call .\stop_local_api.bat

echo.
echo [2/2] Note: Please manually close the WSL2 terminal if still open
echo       (Press Ctrl+C in the WSL terminal, then close the window)

echo.
echo ========================================
echo  🛑 Shutdown Complete
echo ========================================
echo.
echo All done! Local server stopped.
echo WSL2 terminal should be closed manually.
echo.
pause

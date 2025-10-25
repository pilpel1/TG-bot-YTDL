@echo off
title Update yt-dlp
echo ========================================
echo  Updating yt-dlp in all environments
echo ========================================
echo.

REM Get project root directory (go up from scripts\windows)
set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"

echo Current directory: %PROJECT_DIR%
echo.

echo [1/3] Updating yt-dlp in Windows virtual environment...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    pip install --upgrade yt-dlp
    echo [OK] Windows venv updated
) else (
    echo [!] Windows venv not found at: %PROJECT_DIR%venv\Scripts\
)

echo.
echo [2/3] Updating yt-dlp in WSL virtual environment...
if exist "venv_wsl" (
    wsl bash -c "cd '%PROJECT_DIR:\=/%' && cd venv_wsl && source bin/activate && pip install --upgrade yt-dlp"
    if %errorlevel% equ 0 (
        echo [OK] WSL venv updated
    ) else (
        echo [!] Failed to update WSL venv
    )
) else (
    echo [!] WSL venv not found at: %PROJECT_DIR%venv_wsl\
)

echo.
echo [3/3] Checking versions...
echo Windows version:
if exist "venv\Scripts\yt-dlp.exe" (
    venv\Scripts\yt-dlp.exe --version
) else (
    echo Not available
)

echo WSL version:
if exist "venv_wsl" (
    wsl bash -c "cd '%PROJECT_DIR:\=/%' && cd venv_wsl && source bin/activate && yt-dlp --version" 2>nul || echo Not available
) else (
    echo Not available
)

echo.
echo ========================================
echo  [OK] Update Complete!
echo ========================================
echo.
pause

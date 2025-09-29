@echo off
@echo [^>^>] Activating virtual environment...

REM Get project root directory (go up from scripts\windows)
set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"

:: הפעלת הסביבה הווירטואלית
call venv\Scripts\activate.bat

@echo [^>^>] Starting the bot...
python bot.py

:: אם הבוט נכבה, נשאיר את החלון פתוח כדי לראות את השגיאה
pause 
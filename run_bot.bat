@echo off
@echo [^>^>] Activating virtual environment...

:: הפעלת הסביבה הווירטואלית
call venv\Scripts\activate.bat

@echo [^>^>] Starting the bot...
python bot.py

:: אם הבוט נכבה, נשאיר את החלון פתוח כדי לראות את השגיאה
pause 
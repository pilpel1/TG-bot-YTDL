@echo off
echo מפעיל את הסביבה הווירטואלית...

:: הפעלת הסביבה הווירטואלית
call venv\Scripts\activate.bat

echo מפעיל את הבוט...
python bot.py

:: אם הבוט נכבה, נשאיר את החלון פתוח כדי לראות את השגיאה
pause 
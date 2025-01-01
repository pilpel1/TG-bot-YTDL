@echo off
echo מתחיל גיבוי קבצים חשובים...

:: גיבוי קבצים חשובים
if not exist "backup" mkdir backup
if not exist "backup\logs" mkdir backup\logs

:: העתקת קובץ הקונפיג
copy .env backup\.env
:: העתקת תיקיית הלוגים
xcopy /s /i /Y logs backup\logs

echo מעדכן את הקוד מ-git...
git fetch origin
git pull origin main

echo משחזר קבצים מגובים...
:: שחזור הקבצים החשובים
copy backup\.env .env
xcopy /s /i /Y backup\logs logs

echo הכל הושלם בהצלחה!
pause 
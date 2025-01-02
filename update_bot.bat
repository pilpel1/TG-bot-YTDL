@echo off
echo מתחיל גיבוי קבצים חשובים...

:: הגדרת בראנץ' ברירת מחדל
set BRANCH=twitter-download

:: אם הועבר פרמטר, השתמש בו כבראנץ'
if not "%1"=="" set BRANCH=%1

:: גיבוי קבצים חשובים
if not exist "backup" mkdir backup
if not exist "backup\logs" mkdir backup\logs

:: העתקת קובץ הקונפיג
copy .env backup\.env
:: העתקת תיקיית הלוגים
xcopy /s /i /Y logs backup\logs

echo מעדכן את הקוד מ-git (בראנץ': %BRANCH%)...
git fetch origin
git pull origin %BRANCH%

echo משחזר קבצים מגובים...
:: שחזור הקבצים החשובים
copy backup\.env .env
xcopy /s /i /Y backup\logs logs

echo הכל הושלם בהצלחה!
pause 
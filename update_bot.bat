@echo off
@echo [^>^>] Starting backup process...

:: הגדרת בראנץ' ברירת מחדל
set BRANCH=main

:: אם הועבר פרמטר, השתמש בו כבראנץ'
if not "%1"=="" set BRANCH=%1

:: גיבוי קבצים חשובים
if not exist "backup" mkdir backup
if not exist "backup\logs" mkdir backup\logs

:: העתקת קובץ הקונפיג
copy .env backup\.env
:: העתקת תיקיית הלוגים
xcopy /s /i /Y logs backup\logs

@echo [^>^>] Updating code from git (branch: %BRANCH%)...
git fetch origin
git pull origin %BRANCH%

@echo [^>^>] Restoring backup files...
:: שחזור הקבצים החשובים
copy backup\.env .env
xcopy /s /i /Y backup\logs logs

@echo [^>^>] Update completed successfully!
pause 
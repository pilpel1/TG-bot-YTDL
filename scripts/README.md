# 📁 Scripts Directory

תיקייה זו מכילה את כל הסקריפטים להפעלה וניהול של הבוט.

## 📂 מבנה התיקיות

```
scripts/
├── windows/          # סקריפטים עבור Windows (.bat)
├── linux/            # סקריפטים עבור Linux (.sh)
└── README.md         # הקובץ הזה
```

## 🪟 Windows Scripts

### סקריפטים עיקריים:
- **`run_bot_advanced_2GB.bat`** - wrapper ל-Windows שפותח חלון WSL ומריץ את מסלול ה-2GB כולו מתוך WSL
- **`run_bot_simple_50MB.bat`** - הפעלת בוט פשוטה (תמיד 50MB)
- **`update_bot.bat`** - עדכון הבוט מ-Git (עם גיבוי)
- **`update_ytdlp.bat`** - עדכון yt-dlp בכל הסביבות

### סקריפטי עזר:
- **`start_local_api.bat`** - הפעלת שרת מקומי בלבד
- **`stop_local_api.bat`** - עצירת שרת מקומי
- **`stop_bot_and_server.bat`** - עצירת הכל
- **`check_local_api.bat`** - בדיקת סטטוס השרת

## 🐧 Linux Scripts

### סקריפטים עיקריים:
- **`run_bot_advanced_2GB.sh`** - מסלול ה-2GB הרשמי: מרים Local API ב-WSL, ממתין ל-readiness, ואז מפעיל את הבוט
- **`run_bot_simple_50MB.sh`** - הפעלת בוט פשוטה (תמיד 50MB)
- **`update_bot.sh`** - עדכון הבוט מ-Git (עם גיבוי)
- **`update_ytdlp.sh`** - עדכון yt-dlp

### סקריפטי עזר:
- **`start_local_api.sh`** - הפעלת שרת מקומי בלבד
- **`stop_local_api.sh`** - עצירת שרת מקומי

## 🚀 איך להשתמש

### מ-Windows:
```bash
# הפעלה מתקדמת - פותחת WSL ומריצה שם את כל מסלול ה-2GB
scripts\windows\run_bot_advanced_2GB.bat

# הפעלה פשוטה - Windows בלבד, תמיד 50MB
scripts\windows\run_bot_simple_50MB.bat

# עדכונים
scripts\windows\update_bot.bat
scripts\windows\update_ytdlp.bat
```

### מ-Linux:
```bash
# הפעלה מלאה ב-WSL/Linux - המסלול הרשמי ל-2GB
scripts/linux/run_bot_advanced_2GB.sh

# הפעלה פשוטה
scripts/linux/run_bot_simple_50MB.sh

# עדכונים
scripts/linux/update_bot.sh
scripts/linux/update_ytdlp.sh
```

## ⚡ תכונות חכמות

- **זיהוי אוטומטי של נתיבים**: כל הסקריפטים מוצאים את תיקיית הפרויקט אוטומטית
- **סגירה אוטומטית**: חלונות מיותרים נסגרים אוטומטית אחרי הצלחה
- **טיפול בשגיאות**: חלונות נשארים פתוחים במקרה של שגיאה לצורך דיבוג
- **עדכון כפול**: סקריפטי העדכון מטפלים גם ב-Windows וגם ב-WSL

## 🔧 הערות טכניות

- סקריפטי Windows משתמשים ב-`%~dp0` למציאת הנתיב
- סקריפטי Linux משתמשים ב-`dirname` ו-`pwd`
- כל הסקריפטים עובדים מכל מיקום בפרויקט
- סקריפטי Linux צריכים הרשאות הרצה (`chmod +x`)
- מסלול `2GB` מנוהל כולו מתוך WSL כדי למנוע בעיות timing בין Windows ל-WSL

# 🎥 בוט טלגרם להורדת סרטונים מיוטיוב

בוט טלגרם שמאפשר להוריד סרטונים מיוטיוב בקלות, עם אפשרות לבחור בין וידאו ואודיו.

## ✨ יכולות

- 📥 הורדת סרטונים מיוטיוב
- 🎵 המרה לפורמט אודיו (MP3)
- 🎬 הורדת וידאו באיכות הגבוהה ביותר
- 🚀 **תמיכה בקבצים גדולים עד 2GB** (דרך Local Bot API Server)
- 📝 שמירת היסטוריית הורדות
- 🔄 ניסיונות חוזרים במקרה של כשלון
- 💬 ממשק משתמש בעברית

## 🚀 התקנה

### דרישות מקדימות

**בסיסי (חובה):**
- Python 3.8 ומעלה
- FFmpeg (מומלץ מאוד - ללא זה חלק מההורדות עלולות להיכשל)

**למצב מתקדם (אופציונלי - רק לקבצים מעל 50MB):**
- WSL2 (ל-Windows)
- Docker (לשרת Local Bot API)
- חשבון טלגרם לקבלת API credentials

### שלבי ההתקנה

1. שכפל את המאגר:
```bash
git clone https://github.com/pilpel1/TG-bot-YTDL.git
cd TG-bot-YTDL
```

2. צור סביבה וירטואלית והפעל אותה:
```bash
# ליצירת סביבה רגילה (Windows/Linux/Mac)
python -m venv venv

# בWindows:
.\venv\Scripts\activate

# בLinux/Mac:
source venv/bin/activate
```

3. התקן את החבילות הנדרשות:
```bash
pip install -r requirements.txt
```

4. **התקן FFmpeg (מומלץ מאוד):**
```bash
# Python package (קל ונוח)
pip install ffmpeg-python

# או התקנה מהמערכת:
# Windows - הורד מ: https://ffmpeg.org/download.html
# Linux/WSL2 (Ubuntu/Debian)
sudo apt install ffmpeg

# macOS (עם Homebrew)
brew install ffmpeg
```

5. צור קובץ `.env`:
   - העתק את הקובץ `.env.example` ל-`.env`
   - הכנס את הטוקן של הבוט שלך (ראה הוראות בהמשך)
   - אם תרצה מצב מתקדם (2GB) - הוסף גם API credentials

### 🤖 יצירת בוט טלגרם

1. פתח צ'אט עם [@BotFather](https://t.me/BotFather)
2. שלח את הפקודה `/newbot`
3. בחר שם לבוט
4. בחר שם משתמש לבוט (חייב להסתיים ב-bot)
5. העתק את הטוקן שקיבלת לקובץ `.env`

## ⚡ הגדרה מתקדמת (אופציונלי) - תמיכה בקבצים עד 2GB

רק אם אתה רוצה לשלוח קבצים גדולים מ-50MB:

### 🔑 קבלת API credentials

1. כנס ל-[my.telegram.org](https://my.telegram.org)
2. התחבר עם מספר הטלפון שלך
3. לחץ על "API development tools"
4. צור אפליקציה חדשה (תן שם כלשהו)
5. העתק את `api_id` ו-`api_hash` לקובץ `.env`

### 🐳 התקנת WSL2 ו-Docker (Windows בלבד)

התקנת הכלים הנדרשים:

```bash
# התקנת WSL2 (ב-PowerShell כמנהל)
wsl --install

# התקנת Docker ב-WSL2
sudo apt update
sudo apt install docker.io
sudo systemctl start docker
sudo usermod -aG docker $USER

# התקנת ffmpeg (מומלץ)
sudo apt install ffmpeg
```

## 🎯 שימוש

יש שתי דרכים להפעיל את הבוט:

### 🔸 הפעלה פשוטה (מגבלה 50MB)

להפעלה מהירה עם Telegram Bot API הרגיל:

1. **שנה בקוד** שני קבצים:

**ב-`bot.py`** - הערה את ה-base_url:
```python
# הערה או מחק את השורות האלה:
# .base_url("http://localhost:8081/bot")
# .base_file_url("http://localhost:8081/file/bot")
```

**ב-`config.py`** - ודא שהמגבלה מוגדרת ל-50MB:
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB - for standard Telegram Bot API
# MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - for Local Bot API Server mode
```

2. **הפעל את הבוט**:
```bash
# בWindows
.\venv\Scripts\activate
python bot.py

# בLinux/Mac  
source venv/bin/activate
python bot.py
```

### 🚀 הפעלה מתקדמת (מגבלה 2GB)

לשליחת קבצים גדולים דרך Local Bot API Server:

**דרישות:** API credentials מ-my.telegram.org, WSL2, Docker

1. **עדכן הגדרות בקוד** - ב-`config.py` החלף ל-2GB:
```python
# MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB - for standard Telegram Bot API
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - for Local Bot API Server mode
```

2. **הכן את הסביבה ב-WSL2**:
```bash
# הפעל ב-WSL2
wsl
cd /mnt/c/path/to/your/project

# צור סביבה וירטואלית ל-WSL2 (אם עדיין לא קיימת)
python3 -m venv venv_wsl
```

3. **הפעל את Local Bot API Server**:
```bash
# אוטומטית (מקובץ .env)
./start_local_api.bat

# או ידנית
docker run -d --name telegram-bot-api -p 8081:8081 \
  -e TELEGRAM_API_ID=your_api_id \
  -e TELEGRAM_API_HASH=your_api_hash \
  aiogram/telegram-bot-api:latest --local
```

4. **הפעל את הבוט ב-WSL2**:
```bash
source venv_wsl/bin/activate
python bot.py
```

5. **לעצירה**:
```bash
./stop_local_api.bat
```

### שימוש בבוט

1. פתח צ'אט עם הבוט בטלגרם
2. שלח את הפקודה `/start`
3. שלח קישור ליוטיוב
4. בחר אם ברצונך להוריד אודיו או וידאו

## 📁 מבנה הפרויקט

```
TG-bot-YTDL/
├── bot.py                 # קוד הבוט הראשי
├── bot_handlers.py        # מטפלי הודעות
├── download_manager.py    # ניהול הורדות
├── config.py             # הגדרות ומשתנים
├── utils.py              # פונקציות עזר
├── requirements.txt      # חבילות נדרשות
├── .env                  # הגדרות (לא לשיתוף!)
├── .env.example          # דוגמה להגדרות
├── start_local_api.bat   # סקריפט להפעלת שרת מקומי
├── stop_local_api.bat    # סקריפט לעצירת שרת מקומי
├── downloads/            # תיקיית הורדות זמנית
└── logs/                 # היסטוריית הורדות
```

## 🔒 אבטחה

- אל תשתף את קובץ `.env` שלך (מכיל BOT_TOKEN ו-API credentials)
- הקובץ נמצא ב-`.gitignore` כדי למנוע העלאה בטעות
- כל הקבצים המורדים נמחקים אוטומטית אחרי השליחה
- ה-API credentials משמשים רק לחיבור לשרת המקומי

## 🤝 תרומה

מוזמנים לפתוח issues או להציע שינויים דרך pull requests!

## 📝 רישיון

MIT License - ראה קובץ `LICENSE` לפרטים נוספים. 
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

- Python 3.8 ומעלה
- FFmpeg (נדרש להמרת אודיו)
- WSL2 (ל-Windows - לתמיכה בקבצים גדולים)
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
python -m venv venv
# בווינדוס:
.\venv\Scripts\activate
# בלינוקס/מאק:
source venv/bin/activate
```

3. התקן את החבילות הנדרשות:
```bash
pip install -r requirements.txt
```

4. צור קובץ `.env`:
   - העתק את הקובץ `.env.example` ל-`.env`
   - הכנס את הטוקן של הבוט שלך וה-API credentials (ראה הוראות בהמשך)

### 🤖 יצירת בוט טלגרם

1. פתח צ'אט עם [@BotFather](https://t.me/BotFather)
2. שלח את הפקודה `/newbot`
3. בחר שם לבוט
4. בחר שם משתמש לבוט (חייב להסתיים ב-bot)
5. העתק את הטוקן שקיבלת לקובץ `.env`

### 🔑 קבלת API credentials לתמיכה בקבצים גדולים

להורדת קבצים עד 2GB (במקום 50MB):

1. כנס ל-[my.telegram.org](https://my.telegram.org)
2. התחבר עם מספר הטלפון שלך
3. לחץ על "API development tools"
4. צור אפליקציה חדשה (תן שם כלשהו)
5. העתק את `api_id` ו-`api_hash` לקובץ `.env`

### 🐳 הגדרת Local Bot API Server (ל-WSL2)

התקנת WSL2 ו-Docker:

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

### הפעלה רגילה (מגבלה 50MB)

```bash
python bot.py
```

### הפעלה עם תמיכה בקבצים גדולים (עד 2GB)

1. הפעל את Local Bot API Server:
```bash
# ב-WSL2
wsl
cd /mnt/c/path/to/your/project
docker run -d --name telegram-bot-api -p 8081:8081 \
  -e TELEGRAM_API_ID=your_api_id \
  -e TELEGRAM_API_HASH=your_api_hash \
  aiogram/telegram-bot-api:latest --local
```

2. הפעל את הבוט ב-WSL2:
```bash
source venv_wsl/bin/activate
python bot.py
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
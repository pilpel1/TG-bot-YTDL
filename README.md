# 🎥 בוט טלגרם להורדת סרטונים מיוטיוב

בוט טלגרם שמאפשר להוריד סרטונים מיוטיוב בקלות, עם אפשרות לבחור בין וידאו ואודיו.

## ✨ יכולות

- 📥 הורדת סרטונים מיוטיוב
- 🎵 המרה לפורמט אודיו (MP3)
- 🎬 הורדת וידאו באיכות הגבוהה ביותר
- 📝 שמירת היסטוריית הורדות
- 🔄 ניסיונות חוזרים במקרה של כשלון
- 💬 ממשק משתמש בעברית

## 🚀 התקנה

### דרישות מקדימות

- Python 3.8 ומעלה
- FFmpeg (נדרש להמרת אודיו)

### שלבי ההתקנה

1. שכפל את המאגר:
```bash
git clone [URL של המאגר שלך]
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
   - הכנס את הטוקן של הבוט שלך (ראה הוראות בהמשך)

### 🤖 יצירת בוט טלגרם

1. פתח צ'אט עם [@BotFather](https://t.me/BotFather)
2. שלח את הפקודה `/newbot`
3. בחר שם לבוט
4. בחר שם משתמש לבוט (חייב להסתיים ב-bot)
5. העתק את הטוקן שקיבלת לקובץ `.env`

## 🎯 שימוש

1. הפעל את הבוט:
```bash
python bot.py
```

2. פתח צ'אט עם הבוט בטלגרם
3. שלח את הפקודה `/start`
4. שלח קישור ליוטיוב
5. בחר אם ברצונך להוריד אודיו או וידאו

## 📁 מבנה הפרויקט

```
TG-bot-YTDL/
├── bot.py           # קוד הבוט הראשי
├── requirements.txt # חבילות נדרשות
├── .env            # הגדרות (לא לשיתוף!)
├── .env.example    # דוגמה להגדרות
├── downloads/      # תיקיית הורדות זמנית
└── logs/           # היסטוריית הורדות
```

## 🔒 אבטחה

- אל תשתף את קובץ `.env` שלך
- הקובץ נמצא ב-`.gitignore` כדי למנוע העלאה בטעות
- כל הקבצים המורדים נמחקים אוטומטית אחרי השליחה

## 🤝 תרומה

מוזמנים לפתוח issues או להציע שינויים דרך pull requests!

## 📝 רישיון

MIT License - ראה קובץ `LICENSE` לפרטים נוספים. 
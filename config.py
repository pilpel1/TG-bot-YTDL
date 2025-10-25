import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("Please set BOT_TOKEN in .env file")

# Paths
DOWNLOADS_DIR = Path('downloads')
LOGS_DIR = Path('logs')

# Create necessary directories
DOWNLOADS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Download settings - auto-detect based on Local API Server availability
try:
    import requests
    response = requests.get("http://localhost:8081", timeout=2)
    if response.status_code == 404:  # Server is running but endpoint doesn't exist - that's normal
        MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - for Local Bot API Server mode
        print("Local API Server detected - 2GB file limit enabled")
    else:
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB - for standard Telegram Bot API
        print("Using standard Telegram API - 50MB file limit")
except:
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB - for standard Telegram Bot API
    print("Local API Server not available - using 50MB file limit")

# Quality levels for YouTube videos
YOUTUBE_QUALITY_LEVELS = [
    {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]',
        'quality_name': 'איכות גבוהה'
    },
    {
        'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
        'quality_name': 'איכות רגילה'
    },
    {
        'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]',
        'quality_name': 'איכות נמוכה'
    }
]

# Default format for other platforms
DEFAULT_FORMAT = {
    'format': 'best',
    'quality_name': 'איכות מקסימלית'
}

# Version info
VERSION = "0.5.3"
CHANGELOG = """🆕 גרסה 0.5.3:
🎵 תיקון באג הורדת אודיו ושיפורים טכניים
• תיקון באג קריטי: הבוט הוריד וידאו מלא במקום אודיו בלבד
• אינטגרציה עם FFmpeg לחילוץ אודיו אמיתי (הפחתת גודל פי 5-6!)
• זיהוי אוטומטי של FFmpeg בהפעלת הבוט
• שיפורי בחירת פורמט YouTube וטיפול בבעיות nsig/SABR
• הוראות התקנה מפורטות של FFmpeg בתיעוד
• תיקון תצוגת אימוג'ים בסקריפטי Windows""" 
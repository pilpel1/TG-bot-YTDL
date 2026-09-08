import os
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("Please set BOT_TOKEN in .env file")

LOCAL_API_HOST = "http://localhost:8081"
LOCAL_API_BASE_URL = f"{LOCAL_API_HOST}/bot"
LOCAL_API_FILE_URL = f"{LOCAL_API_HOST}/file/bot"


def is_local_api_available(timeout=5):
    """Check the real Bot API endpoint, not just the HTTP listener."""
    try:
        response = requests.get(f"{LOCAL_API_BASE_URL}{BOT_TOKEN}/getMe", timeout=timeout)
        if not response.ok:
            return False

        payload = response.json()
        return payload.get("ok") is True
    except Exception:
        return False

# Paths
DOWNLOADS_DIR = Path('downloads')
LOGS_DIR = Path('logs')
DATA_DIR = Path('data')

# Create necessary directories
DOWNLOADS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Download settings - auto-detect based on real Local API availability
LOCAL_API_AVAILABLE = is_local_api_available()

if LOCAL_API_AVAILABLE:
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - for Local Bot API Server mode
    print("Local API Server detected - 2GB file limit enabled")
else:
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

# Facebook cookies file path (Netscape format, exported from browser)
FACEBOOK_COOKIES_FILE = Path(os.getenv('FACEBOOK_COOKIES_FILE', 'facebook_cookies.txt'))

# מיקסים של יוטיוב נבנים דינמית ואין להם "סוף" אמיתי - כדי שלא יהיה אפשר
# להוריד בטעות מאות סרטונים ממיקס, יש תקרה קשיחה. פלייליסטים רגילים
# (סופיים באמת) לא מוגבלים בזה.
MAX_MIX_DOWNLOAD_LIMIT = 100

# חיפוש יוטיוב בטקסט חופשי
YOUTUBE_SEARCH_RESULTS_LIMIT = 5
YOUTUBE_SEARCH_MIN_QUERY_LENGTH = 3
YOUTUBE_SEARCH_MAX_QUERY_LENGTH = 100

# עדכון yt-dlp אוטומטי (systemd). אפשר לדרוס ב-.env בלי לגעת בקוד.
def _env_int(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return int(raw)


def _env_float(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return float(raw)


def _env_id_list(name):
    """רשימת Telegram user IDs מופרדות בפסיק. ריק = אף אחד."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return []
    ids = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        ids.append(int(part))
    return ids


def _env_hour_list(name, default):
    """רשימת שעות 0-23 מופרדות בפסיק. ריק = כבוי."""
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    if raw.strip() == '':
        return []
    hours = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        hour = int(part)
        if hour < 0 or hour > 23:
            raise ValueError(f'{name} hours must be 0-23, got {hour}')
        if hour not in hours:
            hours.append(hour)
    return sorted(hours)


YTDLP_UPDATE_HOUR = _env_int('YTDLP_UPDATE_HOUR', 1)
YTDLP_UPDATE_MAX_WAIT_HOURS = _env_float('YTDLP_UPDATE_MAX_WAIT_HOURS', 4)
YTDLP_UPDATE_TIMEZONE = os.getenv('YTDLP_UPDATE_TIMEZONE', 'Asia/Jerusalem') or 'Asia/Jerusalem'
YTDLP_PENDING_UPDATE_FLAG = DATA_DIR / 'pending_ytdlp_update'
MAINTENANCE_USER_MESSAGE = (
    'הבוט בעבודות תחזוקה עכשיו. נא לשלוח את הקישור שוב בעוד כמה דקות 🔄'
)

# מעקב ערוצי יוטיוב — cron פנימי. CHANNEL_WATCH_HOURS=8,20 (ברירת מחדל).
# רשימה ריקה ב-.env מכבה את הבדיקה. איכות וידאו קבועה: "רגילה" (720).
CHANNEL_WATCH_HOURS = _env_hour_list('CHANNEL_WATCH_HOURS', [8, 20])
CHANNEL_WATCH_TIMEZONE = (
    os.getenv('CHANNEL_WATCH_TIMEZONE') or YTDLP_UPDATE_TIMEZONE or 'Asia/Jerusalem'
)
CHANNEL_WATCH_FETCH_LIMIT = _env_int('CHANNEL_WATCH_FETCH_LIMIT', 20)
CHANNEL_WATCH_MAX_PER_USER = _env_int('CHANNEL_WATCH_MAX_PER_USER', 10)
CHANNEL_WATCH_NOTIFIED_CAP = _env_int('CHANNEL_WATCH_NOTIFIED_CAP', 200)

# אדמינים לפקודות פנימיות (/broadcast). ריק = אף אחד. לא לשים בגיט — רק ב-.env
ADMIN_USER_IDS = frozenset(_env_id_list('ADMIN_USER_IDS'))

# Version info
VERSION = "0.13.0"
CHANGELOG = """🆕 גרסה 0.13.0:
📣 שידור הודעה לאדמין
• /broadcast — שליחת הודעה או תמונה לכל מי שכבר דיבר עם הבוט (כולל אותך)
• דורש אישור לפני השידור; מי שחסם את הבוט נספר ולא עוצר את השאר
• תפריט אדמין עם פקודות ניהול נוספות
• שם חסר מוצג כמספר, השידור לא נשבר"""

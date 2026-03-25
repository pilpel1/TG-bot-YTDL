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

# Create necessary directories
DOWNLOADS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

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

# Version info
VERSION = "0.6.0"
CHANGELOG = """🆕 גרסה 0.6.0:
📘 שיפור תמיכה בהורדה מפייסבוק
• תמיכה בכל סוגי קישורי פייסבוק (Reels, Watch, Stories, Groups, Posts)
• הורדה מאומתת עם cookies מהדפדפן (Netscape format)
• נורמליזציה חכמה של URL-ים (fb.watch, share links, mobile links)
• הודעות שגיאה ברורות + פקודת /fb_help עם הנחיות הגדרה
• fallback חכם לפורמטים שונים""" 
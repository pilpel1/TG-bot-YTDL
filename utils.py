import re
import asyncio
import telegram
import shutil
import os
import uuid
import yt_dlp
from logger_setup import logger
from config import DOWNLOADS_DIR

# Maximum caption length for Telegram (1024 characters)
MAX_CAPTION_LENGTH = 1024
COMMON_YOUTUBE_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240, 144]

# בדיקה אם FFmpeg זמין
_ffmpeg_available = None

def is_ffmpeg_available():
    """בודק אם FFmpeg מותקן במערכת"""
    global _ffmpeg_available
    if _ffmpeg_available is None:
        _ffmpeg_available = shutil.which('ffmpeg') is not None
    return _ffmpeg_available

def check_ffmpeg_on_startup():
    """בדיקת FFmpeg בהפעלת הבוט - מציג הודעה פעם אחת"""
    if is_ffmpeg_available():
        logger.info("FFmpeg detected - audio extraction will be available")
    else:
        logger.warning("FFmpeg not found - audio downloads may result in larger video files")
    return is_ffmpeg_available()

def clean_filename(filename):
    """מנקה שם קובץ מתווים לא חוקיים ומקצר אותו אם צריך"""
    # מחליף תווים לא חוקיים ברווח
    filename = re.sub(r'[<>:"/\\|?*\u0000-\u001F\u007F-\u009F]', ' ', filename)
    
    # מסיר אימוג'ים ותווים מיוחדים
    filename = ''.join(char for char in filename if ord(char) < 65536)
    
    # מנקה רווחים מיותרים
    filename = ' '.join(filename.split())
    
    # מגביל את אורך שם הקובץ
    max_length = 100  # Windows מגביל ל-260 תווים כולל הנתיב המלא
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length-len(ext)] + ext
    
    # אם השם ריק אחרי הניקוי, משתמש ב-UUID
    if not filename.strip():
        filename = str(uuid.uuid4())
    
    return filename

def cleanup_temp_files():
    """מנקה קבצים זמניים שנשארו מהורדות קודמות"""
    try:
        temp_files_count = 0
        
        # מוחק קבצי .part
        for file_path in DOWNLOADS_DIR.glob("*.part*"):
            try:
                file_path.unlink()
                temp_files_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
        
        # מוחק קבצי .ytdl
        for file_path in DOWNLOADS_DIR.glob("*.ytdl"):
            try:
                file_path.unlink()
                temp_files_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
        
        # מוחק קבצי thumbnail זמניים (webp שנותרו)
        for file_path in DOWNLOADS_DIR.glob("*.webp"):
            try:
                file_path.unlink()
                temp_files_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
        
        if temp_files_count > 0:
            logger.info(f"Cleaned up {temp_files_count} temporary files from downloads directory")
        else:
            logger.info("No temporary files found to clean up")
            
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def sanitize_filename(filename):
    """Clean filename from special characters"""
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return filename


def build_youtube_quality_option(height):
    """בונה אפשרות איכות דינמית לפי רזולוציה."""
    return {
        'height': int(height),
        'format': (
            f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/'
            f'bestvideo[height<={height}]+bestaudio/'
            f'best[height<={height}][ext=mp4]/'
            f'best[height<={height}]'
        ),
        'quality_name': f'{height}p'
    }


def extract_available_youtube_heights(formats):
    """מחלץ רזולוציות וידאו ייחודיות מתוך רשימת פורמטים של YouTube."""
    heights = set()

    for item in formats or []:
        height = item.get('height')
        if not height:
            continue

        if item.get('vcodec') == 'none':
            continue

        if item.get('ext') == 'mhtml':
            continue

        heights.add(int(height))

    if not heights:
        return []

    preferred_heights = [height for height in COMMON_YOUTUBE_HEIGHTS if height in heights]
    if preferred_heights:
        return preferred_heights

    return sorted(heights, reverse=True)


def fetch_youtube_quality_options(url):
    """שולף מ-YouTube את האיכויות הזמינות בפועל עבור סרטון בודד."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'noplaylist': True,
        'socket_timeout': 30,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info or 'entries' in info:
        return []

    return [
        build_youtube_quality_option(height)
        for height in extract_available_youtube_heights(info.get('formats'))
    ]


def estimate_media_size(info):
    """מחזיר גודל צפוי בבתים עבור הפורמט שנבחר."""
    selected_formats = info.get('requested_formats') or [info]
    total_size = 0
    used_approximation = False
    has_size_data = False

    for item in selected_formats:
        exact_size = item.get('filesize')
        approx_size = item.get('filesize_approx')

        if exact_size:
            total_size += int(exact_size)
            has_size_data = True
        elif approx_size:
            total_size += int(approx_size)
            used_approximation = True
            has_size_data = True
        else:
            used_approximation = True

    if not has_size_data:
        return None, True

    return total_size, used_approximation


def format_file_size(size_bytes):
    """ממיר גודל בבתים למחרוזת קריאה לאדם."""
    if size_bytes is None:
        return "לא ידוע"

    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == 'B':
                return f"{int(size)}{unit}"
            return f"{size:.2f}{unit}"
        size /= 1024

    return f"{size_bytes}B"

async def safe_edit_message(message, text, retries=3):
    """Helper function to safely edit messages with retries"""
    for attempt in range(retries):
        try:
            return await message.edit_text(text)
        except telegram.error.TimedOut:
            if attempt == retries - 1:
                logger.error(f"Failed to edit message after {retries} attempts")
                return None
            await asyncio.sleep(1)
        except telegram.error.BadRequest as e:
            if "Message is not modified" in str(e):
                return None
            raise

async def safe_send_message(chat, text, retries=3):
    """Helper function to safely send messages with retries"""
    for attempt in range(retries):
        try:
            return await chat.reply_text(text)
        except telegram.error.TimedOut:
            if attempt == retries - 1:
                logger.error(f"Failed to send message after {retries} attempts")
                return None
            await asyncio.sleep(1)

def split_long_text(text, max_length=MAX_CAPTION_LENGTH):
    """
    חוצה טקסט ארוך למספר חלקים:
    - החלק הראשון: עד 1024 תווים (למדיה עם caption)
    - חלקים נוספים: עד 4096 תווים כל אחד (הודעות טקסט רגילות)
    
    Args:
        text (str): הטקסט המקורי
        max_length (int): האורך המקסימלי לחלק הראשון (ברירת מחדל: 1024)
    
    Returns:
        list: רשימת חלקי הטקסט
    """
    if not text:
        return []
    
    # אם הטקסט קצר מהמגבלה הראשונה - מחזירים אותו כמו שהוא
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    start = 0
    is_first_chunk = True
    
    while start < len(text):
        # החלק הראשון מוגבל ל-1024, השאר ל-4096
        current_max_length = max_length if is_first_chunk else 4096
        end = start + current_max_length
        
        # אם זה החלק האחרון
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        
        # חיפוש פסקה חדשה בחלק האחרון של הטקסט (90% מהמגבלה)
        search_start = start + int(current_max_length * 0.9)
        newline_pos = text.rfind('\n', search_start, end - 1)
        
        if newline_pos > search_start:
            # מצאנו פסקה חדשה - נחתוך שם
            chunks.append(text[start:newline_pos].strip())
            start = newline_pos + 1
        else:
            # אין פסקה חדשה - חיפוש רווח
            space_pos = text.rfind(' ', search_start, end - 1)
            if space_pos > search_start:
                chunks.append(text[start:space_pos].strip())
                start = space_pos + 1
            else:
                # חיתוך קשיח במגבלה
                safe_end = start + current_max_length - 1
                chunks.append(text[start:safe_end].strip())
                start = safe_end
        
        is_first_chunk = False
    
    return [chunk for chunk in chunks if chunk]

async def send_video_with_long_caption(message, video_file, video_info, **kwargs):
    """
    שולח סרטון עם caption ארוך, מחלק את ה-caption למספר הודעות במידת הצורך
    
    Args:
        message: הודעת הטלגרם המקורית
        video_file: קובץ הסרטון
        video_info: מידע על הסרטון (title, description, uploader)
        **kwargs: פרמטרים נוספים לפונקציית reply_video
    
    Returns:
        הודעת הסרטון שנשלחה
    """
    # בניית הטקסט המלא
    title = video_info.get('title', '')
    description = video_info.get('description', '')
    uploader = video_info.get('uploader', 'Unknown')
    
    if title or description:
        full_text = f"{title}\n\n{description}" if title and description else (title or description)
    else:
        full_text = f"Video by {uploader}"
    
    # חלוקת הטקסט
    text_chunks = split_long_text(full_text)
    
    if not text_chunks:
        text_chunks = [f"Video by {uploader}"]
    
    # שליחת הסרטון עם החלק הראשון - בכל מקרה לא יותר מ-1024
    if text_chunks:
        first_caption = text_chunks[0]
        if len(first_caption) > 1020:  # מעט מקום לבטיחות
            first_caption = first_caption[:1020]
    else:
        first_caption = f"Video by {uploader}"
    
    # הסרת caption מ-kwargs כדי להימנע מכפילות
    kwargs.pop('caption', None)
    
    try:
        video_message = await message.reply_video(
            video_file,
            caption=first_caption,
            **kwargs
        )
        
        # שליחת החלקים הנוספים כהודעות נפרדות
        for chunk in text_chunks[1:]:
            if chunk.strip():
                await message.reply_text(chunk)
        
        return video_message
        
    except Exception as e:
        logger.error(f"Error sending video with long caption: {e}")
        raise
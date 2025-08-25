import re
import asyncio
import telegram
from logger_setup import logger

# Maximum caption length for Telegram (1024 characters)
MAX_CAPTION_LENGTH = 1024

def sanitize_filename(filename):
    """Clean filename from special characters"""
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return filename

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
    חוצה טקסט ארוך למספר חלקים שכל אחד מהם לא עובר את הגבלת האורך של טלגרם
    
    Args:
        text (str): הטקסט המקורי
        max_length (int): האורך המקסימלי לכל חלק (ברירת מחדל: 1024)
    
    Returns:
        list: רשימת חלקי הטקסט
    """
    if not text or len(text) <= max_length:
        return [text] if text else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_length
        
        # אם זה החלק האחרון
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        
        # חיפוש פסקה חדשה בין תו 900 ל-1023
        search_start = start + 900 if start + 900 < end else start
        newline_pos = text.rfind('\n', search_start, end - 1)  # -1 כדי לא לחרוג מ-1023
        
        if newline_pos > search_start:
            # מצאנו פסקה חדשה - נחתוך שם
            chunks.append(text[start:newline_pos].strip())
            start = newline_pos + 1
        else:
            # אין פסקה חדשה - חיפוש רווח
            space_pos = text.rfind(' ', search_start, end - 1)  # -1 כדי לא לחרוג מ-1023
            if space_pos > search_start:
                chunks.append(text[start:space_pos].strip())
                start = space_pos + 1
            else:
                # חיתוך קשיח ב-1023 כדי לא לחרוג
                chunks.append(text[start:start + 1023].strip())
                start = start + 1023
    
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
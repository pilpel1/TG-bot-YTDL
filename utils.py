import re
import asyncio
import telegram
from logger_setup import logger

# Maximum caption length for Telegram (4096 characters)
MAX_CAPTION_LENGTH = 4096

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
        max_length (int): האורך המקסימלי לכל חלק (ברירת מחדל: 4096)
    
    Returns:
        list: רשימת חלקי הטקסט
    """
    if not text or len(text) <= max_length:
        return [text] if text else []
    
    # ניסיון לחתוך על פי פסקאות (שורות ריקות)
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    
    for paragraph in paragraphs:
        # אם הפסקה בעצמה ארוכה מדי, נחתוך אותה
        if len(paragraph) > max_length:
            # אם יש חלק נוכחי, נוסיף אותו קודם
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            # נחתוך את הפסקה הארוכה לפי משפטים
            sentences = paragraph.split('. ')
            for i, sentence in enumerate(sentences):
                sentence_to_add = sentence + ('. ' if i < len(sentences) - 1 else '')
                
                # אם המשפט בעצמו ארוך מדי, נחתוך בכוח
                if len(sentence_to_add) > max_length:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                        current_chunk = ""
                    
                    # חתך בכוח לפי אורך
                    while len(sentence_to_add) > max_length:
                        chunks.append(sentence_to_add[:max_length].strip())
                        sentence_to_add = sentence_to_add[max_length:]
                    
                    if sentence_to_add:
                        current_chunk = sentence_to_add
                
                # בדיקה אם אפשר להוסיף למשפט הנוכחי
                elif len(current_chunk) + len(sentence_to_add) <= max_length:
                    current_chunk += sentence_to_add
                else:
                    # הוספת החלק הנוכחי והתחלת חדש
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence_to_add
        
        # פסקה רגילה
        elif len(current_chunk) + len(paragraph) + 2 <= max_length:  # +2 for \n\n
            if current_chunk:
                current_chunk += '\n\n' + paragraph
            else:
                current_chunk = paragraph
        else:
            # הפסקה לא נכנסת, נוסיף את החלק הנוכחי ונתחיל חדש
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = paragraph
    
    # הוספת החלק האחרון
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

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
    
    # שליחת הסרטון עם החלק הראשון
    first_caption = text_chunks[0] if text_chunks else ""
    
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
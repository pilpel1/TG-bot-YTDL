import os
import yt_dlp
import telegram
from pathlib import Path
from logger_setup import logger
from config import DOWNLOADS_DIR, MAX_FILE_SIZE

async def safe_edit_message(message, text):
    """עדכון הודעה עם טיפול בשגיאות"""
    try:
        await message.edit_text(text)
    except telegram.error.BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise

async def safe_send_message(message, text):
    """שליחת הודעה עם טיפול בשגיאות"""
    try:
        await message.reply_text(text)
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")

async def download_with_quality(context, status_message, url, download_mode, quality, quality_levels):
    """הורדת קובץ באיכות ספציפית"""
    try:
        current_file = None
        thumbnail_file = None
        format_spec = quality['format']
        
        if download_mode == 'audio':
            format_spec = 'bestaudio[ext=m4a]/best[ext=m4a]/bestaudio'
            
        ydl_opts = {
            'format': format_spec,
            'outtmpl': str(DOWNLOADS_DIR / '%(title)s.%(ext)s'),
            'writethumbnail': True if download_mode == 'video' else False,
            'postprocessors': [{
                'key': 'FFmpegThumbnailsConvertor',
                'format': 'jpg',
            }] if download_mode == 'video' else [],
            'noplaylist': True,
            'socket_timeout': 120,
        }
        
        await safe_edit_message(
            status_message,
            f'מוריד את הקובץ ב{quality["quality_name"]}... ⏳'
        )
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            current_file = Path(ydl.prepare_filename(info))
            
            # שיפוש התמונה המקדימה בכל הפורמטים האפשריים
            if download_mode == 'video':
                base_path = str(current_file).rsplit('.', 1)[0]
                for ext in ['.jpg', '.webp', '.png']:
                    thumb_path = base_path + ext
                    if os.path.exists(thumb_path):
                        thumbnail_file = Path(thumb_path)
                        break
            
            if not current_file.exists():
                await safe_edit_message(status_message, 'לא הצלחתי להוריד את הקובץ 😕')
                return
                
            size_mb = os.path.getsize(current_file) / (1024 * 1024)
            logger.info(f"File size: {size_mb}MB")
            
            if size_mb <= MAX_FILE_SIZE / (1024 * 1024):
                try:
                    with open(current_file, 'rb') as f:
                        if download_mode == 'audio':
                            await status_message.reply_audio(
                                f,
                                title=info.get('title', 'Audio'),
                                performer=info.get('uploader', 'Unknown'),
                                duration=info.get('duration'),
                                read_timeout=120,
                                write_timeout=120,
                                connect_timeout=120,
                                pool_timeout=120
                            )
                        else:
                            # שליחת הוידאו עם התמונה המקדימה אם קיימת
                            thumbnail_data = None
                            if thumbnail_file and thumbnail_file.exists():
                                try:
                                    with open(thumbnail_file, 'rb') as thumb:
                                        thumbnail_data = thumb.read()
                                except Exception as e:
                                    logger.error(f"Error reading thumbnail: {e}")
                            
                            await status_message.reply_video(
                                f,
                                caption=info.get('title', ''),
                                duration=info.get('duration'),
                                width=info.get('width', 0),
                                height=info.get('height', 0),
                                thumbnail=thumbnail_data if thumbnail_data else None,
                                supports_streaming=True,
                                read_timeout=120,
                                write_timeout=120,
                                connect_timeout=120,
                                pool_timeout=120
                            )
                            
                    if current_file and current_file.exists():
                        current_file.unlink()
                    if thumbnail_file and thumbnail_file.exists():
                        thumbnail_file.unlink()
                        
                    quality_msg = f" ({quality['quality_name']})" if quality['quality_name'] != 'איכות רגילה' else ""
                    await safe_send_message(status_message, f'הנה הקובץ שלך!{quality_msg} 🎉')
                    context.user_data.pop('current_quality_index', None)
                    logger.info("File sent successfully")
                
                except telegram.error.TimedOut:
                    logger.error("Timeout while sending file")
                    await safe_send_message(
                        status_message,
                        'זמן השליחה פג. הקובץ הורד בהצלחה אבל יש בעיה בשליחה. אנא נסה שוב.'
                    )
                    return
            
            else:
                await safe_edit_message(
                    status_message,
                    f'הקובץ גדול מדי ({size_mb:.1f}MB). נסה באיכות נמוכה יותר או סרטון קצר יותר.'
                )
                
                if current_file and current_file.exists():
                    current_file.unlink()
                if thumbnail_file and thumbnail_file.exists():
                    thumbnail_file.unlink()
                    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error during download: {error_msg}")
        
        if "Video unavailable" in error_msg:
            await safe_edit_message(status_message, 'הסרטון לא זמין 😕')
        else:
            await safe_edit_message(status_message, 'משהו השתבש בהורדה 😕')
            
        if current_file and current_file.exists():
            current_file.unlink()
        if thumbnail_file and thumbnail_file.exists():
            thumbnail_file.unlink()
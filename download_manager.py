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
        format_spec = quality['format']
        
        if download_mode == 'audio':
            format_spec = 'bestaudio[ext=m4a]/best[ext=m4a]/bestaudio'
            
        ydl_opts = {
            'format': format_spec,
            'outtmpl': str(DOWNLOADS_DIR / '%(title)s.%(ext)s'),
            'noplaylist': True
        }
        
        await safe_edit_message(
            status_message,
            f'מוריד את הקובץ ב{quality["quality_name"]}... ⏳'
        )
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            current_file = Path(ydl.prepare_filename(info))
            
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
                                duration=info.get('duration')
                            )
                        else:
                            await status_message.reply_video(
                                f,
                                caption=info.get('title', '')
                            )
                            
                    if current_file and current_file.exists():
                        current_file.unlink()
                        
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
                    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error during download: {error_msg}")
        
        if "Video unavailable" in error_msg:
            await safe_edit_message(status_message, 'הסרטון לא זמין 😕')
        else:
            await safe_edit_message(status_message, 'משהו השתבש בהורדה 😕')
            
        if current_file and current_file.exists():
            current_file.unlink()
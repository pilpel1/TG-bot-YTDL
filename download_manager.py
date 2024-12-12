import os
import yt_dlp
import telegram
from pathlib import Path
from logger_setup import logger, log_download
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

def get_user_identifier(chat):
    """מחזיר מזהה משתמש - שם משתמש, שם מלא או ID"""
    if chat.username:
        return chat.username
    elif chat.first_name:
        identifier = chat.first_name
        if chat.last_name:
            identifier += f" {chat.last_name}"
        return identifier
    return str(chat.id)

async def download_playlist(context, status_message, url, download_mode, quality):
    """הורדת פלייליסט"""
    try:
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
            'noplaylist': False,
            'socket_timeout': 120,
        }
        
        await safe_edit_message(status_message, 'מתחיל להוריד את הפלייליסט... ⏳')
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' not in info:
                await safe_edit_message(status_message, 'לא מצאתי פלייליסט בקישור הזה 🤔')
                return
                
            total_videos = len(info['entries'])
            status_message = await status_message.reply_text(f'מצאתי {total_videos} סרטונים בפלייליסט. מתחיל להוריד... ⏳')
            
            successful_downloads = 0
            for index, entry in enumerate(info['entries'], 1):
                try:
                    entry_url = entry['webpage_url']
                    await download_with_quality(context, status_message, entry_url, download_mode, quality, None, is_playlist=True)
                    successful_downloads += 1
                    await status_message.edit_text(f'הורדתי {successful_downloads}/{total_videos} סרטונים מהפלייליסט...\n'
                                                f'כרגע: {entry["title"]}')
                except Exception as e:
                    logger.error(f"Error downloading playlist entry {index}: {str(e)}")
                    continue
            
            await status_message.edit_text(f'סיימתי! הורדתי {successful_downloads} מתוך {total_videos} סרטונים מהפלייליסט 🎉')
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error during playlist download: {error_msg}")
        await safe_edit_message(status_message, 'משהו השתבש בהורדת הפלייליסט 😕')

async def download_with_quality(context, status_message, url, download_mode, quality, quality_levels, is_playlist=False):
    """הורדת קובץ באיכות ספציפית"""
    # בדיקה אם זה פלייליסט
    if not is_playlist:
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    await download_playlist(context, status_message, url, download_mode, quality)
                    return
        except Exception:
            pass
    
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
        
        if not is_playlist:
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
                if not is_playlist:
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
                    
                    log_download(
                        username=get_user_identifier(status_message.chat),
                        url=url,
                        download_type=download_mode,
                        filename=current_file.name
                    )
                    
                    if current_file and current_file.exists():
                        current_file.unlink()
                    if thumbnail_file and thumbnail_file.exists():
                        thumbnail_file.unlink()
                        
                    if not is_playlist:
                        quality_msg = f" ({quality['quality_name']})" if quality['quality_name'] != 'איכות רגילה' else ""
                        await safe_send_message(status_message, f'הנה הקובץ שלך!{quality_msg} 🎉')
                        context.user_data.pop('current_quality_index', None)
                    logger.info("File sent successfully")
                
                except telegram.error.TimedOut:
                    logger.error("Timeout while sending file")
                    if not is_playlist:
                        await safe_send_message(
                            status_message,
                            'זמן השליחה פג. הקובץ הורד בהצלחה אבל יש בעיה בשליחה. אנא נסה שוב.'
                        )
                    return
            
            else:
                if not is_playlist:
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
        
        if not is_playlist:
            if "Video unavailable" in error_msg:
                await safe_edit_message(status_message, 'הסרטון לא זמין 😕')
            else:
                await safe_edit_message(status_message, 'משהו השתבש בהורדה 😕')
            
        if current_file and current_file.exists():
            current_file.unlink()
        if thumbnail_file and thumbnail_file.exists():
            thumbnail_file.unlink()
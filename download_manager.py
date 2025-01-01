import os
import yt_dlp
import telegram
from pathlib import Path
from logger_setup import logger, log_download
from config import DOWNLOADS_DIR, MAX_FILE_SIZE
import asyncio
import re
import uuid

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

async def download_playlist(context, status_message, url, download_mode, quality, playlist_info=None):
    """הורדת פלייליסט"""
    try:
        format_spec = quality['format']
        if download_mode == 'audio':
            format_spec = 'bestaudio[ext=m4a]/best[ext=m4a]/bestaudio'
        
        logger.info(f"Starting playlist download for URL: {url}")
        await safe_edit_message(status_message, 'מתחיל להוריד את הפלייליסט... ⏳')
        
        # אופציות בסיסיות להורדה
        ydl_opts = {
            'format': format_spec,
            'outtmpl': str(DOWNLOADS_DIR / '%(title)s.%(ext)s'),
            'writethumbnail': True if download_mode == 'video' else False,
            'postprocessors': [{
                'key': 'FFmpegThumbnailsConvertor',
                'format': 'jpg',
            }] if download_mode == 'video' else [],
            'extract_flat': True,  # רק מידע בסיסי בהתחלה
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'socket_timeout': 30,
            'outtmpl_na_placeholder': 'unknown_title',  # שם ברירת מחדל אם אין כותרת
        }
        
        # קבלת מידע על הפלייליסט
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("Extracting playlist info...")
            result = playlist_info or ydl.extract_info(url, download=False)
            
            if not result:
                raise Exception("Could not extract playlist info")
            
            entries = result.get('entries', [])
            entries = [e for e in entries if e is not None]
            
            if not entries:
                logger.error("No valid entries found in playlist")
                await safe_edit_message(status_message, 'לא מצאתי סרטונים תקינים בפלייליסט 😕')
                return
            
            total_videos = len(entries)
            logger.info(f"Found {total_videos} valid videos in playlist")
            progress_message = await status_message.reply_text(
                f'מצאתי {total_videos} סרטונים בפלייליסט. מתחיל להוריד... ⏳'
            )
            
            successful_downloads = 0
            error_videos = 0
            
            # הורדת כל סרטון
            for index, entry in enumerate(entries, 1):
                current_file = None
                try:
                    video_id = entry.get('id') or entry.get('url')
                    if not video_id:
                        logger.warning(f"No video ID for entry {index}")
                        error_videos += 1
                        continue
                    
                    # עדכון הודעת התקדמות
                    try:
                        await progress_message.delete()
                    except Exception:
                        pass
                        
                    current_title = entry.get('title', f'סרטון #{index}')
                    progress_message = await status_message.reply_text(
                        f'הורדתי {successful_downloads}/{total_videos} סרטונים מהפלייליסט\n'
                        f'עכשיו מוריד: {current_title} ⏳'
                    )
                    
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    logger.info(f"Processing video {index}/{total_videos}: {video_url}")
                    
                    # הורדת הסרטון
                    await download_with_quality(
                        context,
                        status_message,
                        video_url,
                        download_mode,
                        quality,
                        None,
                        is_playlist=True
                    )
                    
                    successful_downloads += 1
                    logger.info(f"Successfully processed video {index}")
                
                except Exception as video_error:
                    logger.error(f"Error processing video {index}: {str(video_error)}")
                    error_videos += 1
            
            # סיכום
            try:
                await progress_message.delete()
            except Exception:
                pass
                
            summary = f'סיימתי! הורדתי {successful_downloads} מתוך {total_videos} סרטונים מהפלייליסט 🎉'
            if error_videos > 0:
                summary += f' ({error_videos} לא זמינים)'
            logger.info(f"Playlist download completed. Success: {successful_downloads}, Errors: {error_videos}")
            await status_message.reply_text(summary)
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Critical error during playlist download: {error_msg}")
        await safe_edit_message(status_message, 'משהו השתבש בהורדת הפלייליסט 😕')

async def download_with_quality(context, status_message, url, download_mode, quality, quality_levels, is_playlist=False):
    """הורדת קובץ באיכות ספציפית"""
    current_file = None
    thumbnail_file = None
    
    try:
        # בדיקה אם זה פלייליסט
        if not is_playlist:
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if 'entries' in info:
                        await download_playlist(context, status_message, url, download_mode, quality)
                        return
            except Exception as e:
                logger.error(f"Error checking if URL is playlist: {str(e)}")
                # ממשיך כאילו זה לא פלייליסט
        
        format_spec = quality['format']
        if download_mode == 'audio':
            format_spec = 'bestaudio[ext=m4a]/best[ext=m4a]/bestaudio'
            
        # פונקציה שמנקה את שם הקובץ לפני היצירה
        def custom_filename(info_dict, *, prefix=''):
            video_title = info_dict.get('title', 'video')
            clean_title = clean_filename(video_title)
            if prefix:
                clean_title = f"{prefix}_{clean_title}"
            ext = info_dict.get('ext', 'mp4')
            return str(DOWNLOADS_DIR / f"{clean_title}.{ext}")
            
        ydl_opts = {
            'format': format_spec,
            'writethumbnail': True if download_mode == 'video' else False,
            'postprocessors': [{
                'key': 'FFmpegThumbnailsConvertor',
                'format': 'jpg',
            }] if download_mode == 'video' else [],
            'noplaylist': True,
            'socket_timeout': 120,
            'outtmpl': '%(title)s.%(ext)s',  # תבנית בסיסית, תשומש על ידי custom_filename
            'outtmpl_na_placeholder': 'unknown_title',
            'progress_hooks': [],
            'outtmpl_func': custom_filename,
            'paths': {'home': str(DOWNLOADS_DIR)},
            'writesubtitles': False,
            'writethumbnail': True if download_mode == 'video' else False,
            'outtmpl_thumbnail': lambda info_dict: custom_filename(info_dict, prefix='thumb')
        }
        
        if not is_playlist:
            await safe_edit_message(
                status_message,
                f'מוריד את הקובץ ב{quality["quality_name"]}... ⏳'
            )
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise Exception("Could not download video")
            
            current_file = Path(ydl.prepare_filename(info))
            
            # שיקוש התמונה המקדימה בכל הפורמטים האפשריים
            if download_mode == 'video':
                base_path = str(current_file).rsplit('.', 1)[0]
                for ext in ['.jpg', '.webp', '.png']:
                    thumb_path = base_path + ext
                    if os.path.exists(thumb_path):
                        thumbnail_file = Path(thumb_path)
                        break
            
            if not current_file.exists():
                raise Exception("File not downloaded")
                
            size_mb = os.path.getsize(current_file) / (1024 * 1024)
            logger.info(f"File size: {size_mb}MB")
            
            if size_mb <= MAX_FILE_SIZE / (1024 * 1024):
                # שליחת הקובץ עם ניסיונות חוזרים
                max_retries = 3
                last_error = None
                
                for attempt in range(max_retries):
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
                        
                        # רישום ההורדה
                        log_download(
                            username=get_user_identifier(status_message.chat),
                            url=url,
                            download_type=download_mode,
                            filename=current_file.name
                        )
                        
                        if not is_playlist:
                            quality_msg = f" ({quality['quality_name']})" if quality['quality_name'] != 'איכות רגילה' else ""
                            await safe_send_message(status_message, f'הנה הקובץ שלך!{quality_msg} 🎉')
                            context.user_data.pop('current_quality_index', None)
                        
                        logger.info("File sent successfully")
                        break  # יציאה מהלולאה אם השליחה הצליחה
                        
                    except telegram.error.TimedOut as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            logger.warning(f"Timeout on attempt {attempt + 1}, retrying...")
                            await asyncio.sleep(2)
                        else:
                            raise Exception(f"Failed after {max_retries} attempts: {str(e)}")
                    
                    except Exception as e:
                        last_error = e
                        raise
            
            else:
                if not is_playlist:
                    await safe_edit_message(
                        status_message,
                        f'הקובץ גדול מדי ({size_mb:.1f}MB). נסה באיכות נמוכה יותר או סרטון קצר יותר.'
                    )
                return False
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error during download: {error_msg}")
        
        if not is_playlist:
            if "Video unavailable" in error_msg:
                await safe_edit_message(status_message, 'הסרטון לא זמין 😕')
            else:
                await safe_edit_message(status_message, 'משהו השתבש בהורדה 😕')
        raise  # מעביר את השגיאה הלאה כדי שdownload_playlist יוכל לטפל בה
    
    finally:
        # ניקוי הקבצים הנוכחיים
        if current_file and current_file.exists():
            try:
                current_file.unlink()
            except Exception as e:
                logger.error(f"Error deleting file {current_file}: {e}")
        
        if thumbnail_file and thumbnail_file.exists():
            try:
                thumbnail_file.unlink()
            except Exception as e:
                logger.error(f"Error deleting thumbnail {thumbnail_file}: {e}")
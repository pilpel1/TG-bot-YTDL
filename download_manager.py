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
        
        # הגדרות בסיסיות עבור yt-dlp
        format_spec = quality['format']
        if download_mode == 'audio':
            format_spec = 'bestaudio[ext=m4a]/best[ext=m4a]/bestaudio'
            
        # פונקציה שמנקה את שם הקובץ לפני היצירה
        def custom_filename(info_dict, *, prefix=''):
            try:
                video_title = info_dict.get('title', 'video')
                clean_title = clean_filename(video_title)
                filename = clean_title
                
                if len(filename.strip()) < 3:
                    video_id = info_dict.get('id', str(uuid.uuid4()))
                    filename = f"{video_id}"
                
                if prefix:
                    filename = f"{prefix}_{filename}"
                    
                ext = info_dict.get('ext', 'mp4')
                full_path = str(DOWNLOADS_DIR / f"{filename}.{ext}")
                
                try:
                    Path(full_path).touch()
                    Path(full_path).unlink()
                    return full_path
                except OSError:
                    video_id = info_dict.get('id', str(uuid.uuid4()))
                    filename = f"{video_id}"
                    if prefix:
                        filename = f"{prefix}_{filename}"
                    return str(DOWNLOADS_DIR / f"{filename}.{ext}")
                    
            except Exception as e:
                logger.error(f"Error in custom_filename: {e}")
                video_id = info_dict.get('id', str(uuid.uuid4()))
                filename = f"{video_id}"
                if prefix:
                    filename = f"{prefix}_{filename}"
                ext = info_dict.get('ext', 'mp4')
                return str(DOWNLOADS_DIR / f"{filename}.{ext}")

        # הגדרות מותאמות עבור Vimeo
        is_vimeo = 'vimeo.com' in url
        ydl_opts = {
            'format': format_spec,
            'writethumbnail': True if download_mode == 'video' else False,
            'postprocessors': [{
                'key': 'FFmpegThumbnailsConvertor',
                'format': 'jpg',
            }] if download_mode == 'video' else [],
            'noplaylist': True,
            'socket_timeout': 120,
            'outtmpl': '%(id)s.%(ext)s',
            'outtmpl_na_placeholder': 'unknown_title',
            'progress_hooks': [],
            'outtmpl_func': custom_filename,
            'paths': {'home': str(DOWNLOADS_DIR)},
            'writesubtitles': False,
            'writethumbnail': True if download_mode == 'video' else False,
            'outtmpl_thumbnail': '%(id)s.%(ext)s',
            'extractor_retries': 3,
            'retries': 5,
            'fragment_retries': 5,
            'skip_download': False,
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://vimeo.com',
                'Referer': 'https://vimeo.com/'
            }
        }

        # הגדרות נוספות עבור Vimeo
        if is_vimeo:
            ydl_opts.update({
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if download_mode == 'video' else 'bestaudio[ext=m4a]/bestaudio',
                'allow_unplayable_formats': True,
                'hls_prefer_native': False,
                'hls_split_discontinuity': True,
                'external_downloader': 'ffmpeg',
                'external_downloader_args': {
                    'ffmpeg_i': [
                        '-headers', 
                        'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        '-reconnect', '1',
                        '-reconnect_streamed', '1',
                        '-reconnect_delay_max', '5'
                    ]
                }
            })

        if not is_playlist:
            await safe_edit_message(
                status_message,
                f'מוריד את הקובץ ב{quality["quality_name"]}... ⏳'
            )
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except yt_dlp.utils.DownloadError as e:
                if "Requested format is not available" in str(e):
                    logger.info("Requested format not available, checking available formats...")
                    ydl_opts['listformats'] = True
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_list:
                        try:
                            formats_info = ydl_list.extract_info(url, download=False)
                            if formats_info and 'formats' in formats_info:
                                available_formats = [f"{f['format_id']}: {f.get('ext', 'N/A')} - {f.get('format_note', 'N/A')}" 
                                                   for f in formats_info['formats']]
                                logger.info(f"Available formats: {available_formats}")
                                
                                if is_vimeo:
                                    # בחירת פורמט ספציפי עבור Vimeo
                                    if download_mode == 'video':
                                        video_formats = [f for f in formats_info['formats'] 
                                                       if f.get('vcodec', 'none') != 'none' 
                                                       and f.get('acodec', 'none') != 'none']
                                        
                                        if not video_formats:
                                            # אם אין פורמטים משולבים, מחפש פורמטים נפרדים
                                            video_formats = [f for f in formats_info['formats'] 
                                                           if f.get('vcodec', 'none') != 'none']
                                            
                                        if video_formats:
                                            video_formats.sort(key=lambda x: int(x.get('height', 0)), reverse=True)
                                            quality_height = int(quality.get('height', 1080))
                                            
                                            chosen_format = None
                                            for fmt in video_formats:
                                                if fmt.get('height', 0) <= quality_height:
                                                    chosen_format = fmt
                                                    break
                                            
                                            if not chosen_format:
                                                chosen_format = video_formats[-1]
                                            
                                            format_spec = chosen_format['format_id']
                                            if chosen_format.get('acodec', 'none') == 'none':
                                                # אם אין אודיו, מחפש פורמט אודיו מתאים
                                                audio_formats = [f for f in formats_info['formats'] 
                                                               if f.get('acodec', 'none') != 'none' 
                                                               and f.get('vcodec', 'none') == 'none']
                                                if audio_formats:
                                                    format_spec = f"{format_spec}+{audio_formats[0]['format_id']}"
                                            
                                            logger.info(f"Selected Vimeo format: {format_spec}")
                                    else:
                                        # עבור אודיו בלבד
                                        audio_formats = [f for f in formats_info['formats'] 
                                                       if f.get('acodec', 'none') != 'none']
                                        if audio_formats:
                                            format_spec = audio_formats[0]['format_id']
                                            logger.info(f"Selected Vimeo audio format: {format_spec}")
                                        else:
                                            raise Exception("Could not find compatible audio format")
                                else:
                                    # טיפול בפורמטים אחרים (לא Vimeo)
                                    if any('m3u8' in str(f.get('protocol', '')) for f in formats_info['formats']):
                                        if download_mode == 'video':
                                            video_formats = [f for f in formats_info['formats'] 
                                                           if 'video only' in str(f.get('format_note', '')) 
                                                           and 'm3u8' in str(f.get('protocol', ''))]
                                            
                                            if video_formats:
                                                video_formats.sort(key=lambda x: int(x.get('height', 0)), reverse=True)
                                                quality_height = int(quality.get('height', 1080))
                                                
                                                chosen_format = None
                                                for fmt in video_formats:
                                                    if fmt.get('height', 0) <= quality_height:
                                                        chosen_format = fmt
                                                        break
                                                
                                                if not chosen_format:
                                                    chosen_format = video_formats[-1]
                                                
                                                format_spec = chosen_format['format_id']
                                                logger.info(f"Selected format: {format_spec} ({chosen_format.get('height', 'N/A')}p)")
                                            else:
                                                raise Exception("Could not find compatible video format")
                                        else:
                                            audio_formats = [f for f in formats_info['formats'] 
                                                           if 'audio only' in str(f.get('format_note', ''))]
                                            if audio_formats:
                                                format_spec = audio_formats[0]['format_id']
                                                logger.info(f"Selected audio format: {format_spec}")
                                            else:
                                                raise Exception("Could not find compatible audio format")
                                    else:
                                        raise Exception("No compatible formats found")
                                
                                # ניסיון הורדה עם הפורמט שנבחר
                                ydl_opts['listformats'] = False
                                ydl_opts['format'] = format_spec
                                logger.info(f"Trying to download with format: {format_spec}")
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                                    info = ydl_retry.extract_info(url, download=True)
                            else:
                                raise Exception("No formats available")
                        except Exception as format_error:
                            logger.error(f"Error checking formats: {str(format_error)}")
                            raise
                else:
                    raise

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
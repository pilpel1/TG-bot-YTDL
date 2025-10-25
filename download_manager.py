import os
import yt_dlp
import telegram
from pathlib import Path
from logger_setup import logger, log_download
from config import DOWNLOADS_DIR, MAX_FILE_SIZE
from utils import send_video_with_long_caption, is_ffmpeg_available, clean_filename
import asyncio
import re
import uuid
import subprocess
import requests

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
            format_spec = 'bestaudio[ext=m4a]/bestaudio[ext=aac]/bestaudio[ext=mp3]'
        
        logger.info(f"Starting playlist download for URL: {url}")
        await safe_edit_message(status_message, 'מתחיל להוריד את הפלייליסט... ⏳')
        
        # הגדרת post-processors לפלייליסט
        playlist_postprocessors = []
        if download_mode == 'video':
            if is_ffmpeg_available():
                playlist_postprocessors.append({
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg',
                })
        elif download_mode == 'audio':
            if is_ffmpeg_available():
                playlist_postprocessors.append({
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                    'preferredquality': '192',
                })
            else:
                logger.warning("FFmpeg not available - downloading audio-only stream without conversion")

        # אופציות בסיסיות להורדה
        ydl_opts = {
            'format': format_spec,
            'outtmpl': str(DOWNLOADS_DIR / '%(title)s.%(ext)s'),
            'writethumbnail': True if download_mode == 'video' else False,
            'postprocessors': playlist_postprocessors,
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
        # המרת קישורי X לטוויטר בתחילת התהליך
        if 'x.com' in url:
            url = url.replace('x.com', 'twitter.com')
            logger.info(f"Converting X URL to Twitter URL: {url}")

        # בדיקה אם זה פלייליסט
        if not is_playlist:
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    # בדיקת תוכן מוגבל
                    if info.get('age_limit', 0) > 0 or info.get('content_warning'):
                        await safe_edit_message(status_message, 'הסרטון מוגבל לצפייה, לא ניתן להוריד ⛔')
                        raise Exception("Sign in to confirm your age")
                    # בדיקת פלייליסט
                    if 'entries' in info:
                        await download_playlist(context, status_message, url, download_mode, quality)
                        return
            except Exception as e:
                if "Sign in to confirm your age" in str(e):
                    await safe_edit_message(status_message, 'הסרטון מוגבל לצפייה, לא ניתן להוריד ⛔')
                    raise
                logger.error(f"Error in pre-check: {str(e)}")

        # הגדרות בסיסיות עבור yt-dlp
        format_spec = quality['format']
        if download_mode == 'audio':
            format_spec = 'bestaudio[ext=m4a]/bestaudio[ext=aac]/bestaudio[ext=mp3]/bestaudio'
            
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

        # הגדרת post-processors
        postprocessors = []
        if download_mode == 'video':
            if is_ffmpeg_available():
                postprocessors.append({
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg',
                })
        elif download_mode == 'audio':
            if is_ffmpeg_available():
                postprocessors.append({
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                    'preferredquality': '192',
                })
            else:
                logger.warning("FFmpeg not available - downloading audio-only stream without conversion")

        ydl_opts = {
            'format': format_spec,
            'writethumbnail': True if download_mode == 'video' else False,
            'postprocessors': postprocessors,
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
            'extractor_retries': 10,
            'retries': 10,
            'fragment_retries': 10,
            'skip_download': False,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1'
            }
        }
        
        # הגדרות ספציפיות לפלטפורמות
        if 'youtube.com' in url or 'youtu.be' in url:
            # הגדרות מיוחדות ל-YouTube כדי לטפל בבעיות nsig החדשות
            youtube_opts = {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['configs'],
                        'skip': ['hls', 'dash']
                    }
                },
                'prefer_free_formats': True,
                'http_headers': {
                    **ydl_opts['http_headers'],
                    'User-Agent': 'com.google.android.youtube/17.31.35 (Linux; U; Android 11) gzip',
                    'X-YouTube-Client-Name': '3',
                    'X-YouTube-Client-Version': '17.31.35'
                }
            }
            
            # רק לוידאו - דורס את הפורמט. לאודיו - שומר על הפורמט שהגדרנו
            if download_mode == 'video':
                youtube_opts['format'] = 'best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best[ext=mp4]/best'
            
            ydl_opts.update(youtube_opts)
        elif 'tiktok.com' in url:
            # המרת קישור מקוצר לקישור מלא
            if 'vt.tiktok.com' in url:
                logger.info("Converting shortened TikTok URL...")
                url = resolve_tiktok_url(url)
                logger.info(f"Resolved URL: {url}")
            
            ydl_opts.update({
                'format': 'best[ext=mp4]/best',
                'extractor_args': {
                    'tiktok': {
                        'embed_url': ['0'],
                        'api_hostname': ['api22-normal-c-useast2a.tiktokv.com'],
                        'app_version': ['2.3.0'],
                        'manifest_app_version': ['2.3.0'],
                        'use_api': ['1']
                    }
                },
                'http_headers': {
                    **ydl_opts['http_headers'],
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://www.tiktok.com/',
                    'Origin': 'https://www.tiktok.com',
                    'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'same-site'
                }
            })
        elif 'twitter.com' in url:
            ydl_opts.update({
                'format': 'best[ext=mp4]/best',
                'http_headers': {
                    **ydl_opts['http_headers'],
                    'Authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
                    'Referer': 'https://twitter.com/',
                    'Origin': 'https://twitter.com',
                    'x-twitter-active-user': 'yes',
                    'x-twitter-auth-type': 'OAuth2Session',
                    'x-twitter-client-language': 'en',
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                'extractor_args': {
                    'twitter': {
                        'api': ['syndication'],
                    }
                }
            })
        elif 'instagram.com' in url:
            ydl_opts.update({
                'format': 'best[ext=mp4]/best',
                'http_headers': {
                    **ydl_opts['http_headers'],
                    'User-Agent': 'Instagram 219.0.0.12.117 Android',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US',
                    'Accept-Encoding': 'gzip, deflate',
                    'X-IG-Capabilities': '3brTvw==',
                    'X-IG-Connection-Type': 'WIFI',
                    'X-IG-App-ID': '567067343352427',
                    'X-FB-HTTP-Engine': 'Liger',
                    'Connection': 'keep-alive',
                    'Pragma': 'no-cache',
                    'Authorization': 'Bearer IGT:2:eyJkc191c2VyX2lkIjoiNTY3MDY3MzQzMzUyNDI3IiwiaWciOiIyMTkuMC4wLjEyLjExNyJ9'
                },
                'extractor_args': {
                    'instagram': {
                        'api_key': ['567067343352427'],
                        'app_version': ['219.0.0.12.117'],
                        'android_release': ['13'],
                        'android_version': ['33'],
                        'phone_manufacturer': ['samsung'],
                        'phone_model': ['SM-G973F'],
                        'phone_device': ['beyond1'],
                        'locale': ['en_US']
                    }
                },
                'outtmpl': str(DOWNLOADS_DIR / '%(uploader)s_%(title)s_%(id)s.%(ext)s'),
                'add_metadata': True,
                'no_check_certificate': True,
                'ignore_no_formats_error': True
            })
        elif 'facebook.com' in url or 'fb.watch' in url:
            # ניקוי והמרת הקישור
            if 'share/v/' in url:
                video_id = url.split('/v/')[-1].split('/')[0]
                url = f'https://www.facebook.com/watch?v={video_id}'
            elif 'fb.watch' in url:
                video_id = url.split('/')[-1].split('?')[0]
                url = f'https://www.facebook.com/watch?v={video_id}'
            
            logger.info(f"Converted Facebook URL: {url}")
            
            ydl_opts.update({
                'format': 'dash,progressive',
                'extract_flat': False,
                'ignore_no_formats_error': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Origin': 'https://www.facebook.com',
                    'Referer': 'https://www.facebook.com/',
                    'Sec-Fetch-Dest': 'empty',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'same-origin'
                }
            })

            # הוספת קוקיז אם הקובץ קיים
            cookies_file = Path('facebook_cookies.txt')
            if cookies_file.exists():
                ydl_opts['cookiefile'] = str(cookies_file)
                logger.info("Using facebook_cookies.txt for download.")

        if not is_playlist:
            await safe_edit_message(
                status_message,
                f'מוריד את הקובץ ב{quality["quality_name"]}... ⏳'
            )
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # ניסיון ראשון - הורדה ישירה
                info = ydl.extract_info(url, download=True)
            except yt_dlp.utils.DownloadError as e:
                error_str = str(e)
                if any(keyword in error_str for keyword in [
                    "Failed to parse XML", 
                    "Requested format is not available",
                    "nsig extraction failed",
                    "Some formats may be missing",
                    "Only images are available"
                ]):
                    logger.info("Retrying with different format selection...")
                    
                    # מנסה עם פורמטים פשוטים יותר - ללא מרוכבים
                    if download_mode == 'audio':
                        fallback_formats = [
                            'bestaudio/best',
                            'worst[acodec!=none]/worst',
                            'best[acodec!=none]/best'
                        ]
                    else:
                        fallback_formats = [
                            'best[height<=720]/best',
                            'worst[height>=360]/worst',
                            'mp4/best',
                            'best[ext=mp4]/best',
                            'best[protocol=https]/best[protocol=http]/best'
                        ]
                    
                    for fallback_format in fallback_formats:
                        try:
                            logger.info(f"Trying format: {fallback_format}")
                            ydl_opts_retry = ydl_opts.copy()
                            ydl_opts_retry.update({
                                'format': fallback_format,
                                'prefer_free_formats': True,
                                'no_check_formats': True,
                                'ignore_no_formats_error': True,
                                'extract_flat': False
                            })
                            # וודא שה-post-processor לאודיו נשמר גם ב-fallback
                            if download_mode == 'audio':
                                ydl_opts_retry['postprocessors'] = postprocessors
                            
                            with yt_dlp.YoutubeDL(ydl_opts_retry) as ydl_retry:
                                info = ydl_retry.extract_info(url, download=True)
                                if info:
                                    logger.info(f"Success with format: {fallback_format}")
                                    break
                                    
                        except Exception as retry_error:
                            logger.warning(f"Format {fallback_format} failed: {str(retry_error)}")
                            continue
                    
                    if not info:
                        logger.error(f"All fallback formats failed for: {url}")
                        raise Exception("All download formats failed")
                else:
                    raise

            if not info:
                raise Exception("Could not download video")
            
            current_file = Path(ydl.prepare_filename(info))
            
            # אם זה אודיו עם post-processor, הקובץ הסופי יהיה עם סיומת m4a
            if download_mode == 'audio' and is_ffmpeg_available():
                # מחפש את הקובץ עם הסיומת הנכונה אחרי ה-post-processing
                base_path = str(current_file).rsplit('.', 1)[0]
                possible_audio_files = [
                    Path(f"{base_path}.m4a"),
                    Path(f"{base_path}.aac"), 
                    Path(f"{base_path}.mp3"),
                    current_file  # הקובץ המקורי אם לא היה post-processing
                ]
                
                for audio_file in possible_audio_files:
                    if audio_file.exists():
                        current_file = audio_file
                        logger.info(f"Audio extracted: {audio_file.name} ({audio_file.stat().st_size / (1024*1024):.2f}MB)")
                        break
            
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
                try:
                    with open(current_file, 'rb') as f:
                        if download_mode == 'audio':
                            await status_message.reply_audio(
                                f,
                                title=info.get('title', 'Audio'),
                                performer=info.get('uploader', 'Unknown'),
                                duration=info.get('duration'),
                                read_timeout=180,
                                write_timeout=180,
                                connect_timeout=180,
                                pool_timeout=180
                            )
                        else:
                            thumbnail_data = None
                            if thumbnail_file and thumbnail_file.exists():
                                try:
                                    with open(thumbnail_file, 'rb') as thumb:
                                        thumbnail_data = thumb.read()
                                except Exception as e:
                                    logger.error(f"Error reading thumbnail: {e}")
                                
                            await send_video_with_long_caption(
                                status_message,
                                f,
                                info,
                                duration=info.get('duration'),
                                width=info.get('width', 0),
                                height=info.get('height', 0),
                                thumbnail=thumbnail_data if thumbnail_data else None,
                                supports_streaming=True,
                                read_timeout=180,
                                write_timeout=180,
                                connect_timeout=180,
                                pool_timeout=180
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
                
                except telegram.error.TimedOut as e:
                    logger.error(f"Timeout during file send: {str(e)}")
                    if not is_playlist:
                        await safe_edit_message(status_message, 'שליחת הקובץ נכשלה עקב זמן ממושך מדי. נסה שוב או בחר באיכות נמוכה יותר.')
                    raise
                
                except Exception as e:
                    logger.error(f"Error sending file: {str(e)}")
                    raise
            
            else:
                if not is_playlist:
                    max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
                    max_size_display = f"{max_size_mb:.0f}MB" if max_size_mb < 1024 else f"{max_size_mb/1024:.0f}GB"
                    await safe_edit_message(
                        status_message,
                        f'הקובץ גדול מדי ({size_mb:.1f}MB). מגבלה מקסימלית: {max_size_display}. נסה באיכות נמוכה יותר.'
                    )
                return False
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error during download: {error_msg}")
        
        if not is_playlist:
            if "Sign in to confirm your age" in error_msg:
                await safe_edit_message(status_message, 'הסרטון מוגבל לצפייה, לא ניתן להוריד ⛔')
                raise  # מעביר את השגיאה ל-error_handler
            elif "Video unavailable" in error_msg:
                await safe_edit_message(status_message, 'הסרטון לא זמין 😕')
            else:
                await safe_edit_message(status_message, 'משהו השתבש בהורדה 😕')
        raise  # מעביר את השגיאה הלאה
    
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

def resolve_tiktok_url(url):
    """מקבל קישור מקוצר של טיקטוק ומחזיר את הקישור המלא"""
    try:
        response = requests.head(url, allow_redirects=True)
        return response.url
    except Exception as e:
        logger.error(f"Error resolving TikTok URL: {e}")
        return url
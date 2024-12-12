import yt_dlp
from pathlib import Path
import telegram
from logger_setup import logger
from config import DOWNLOADS_DIR, MAX_FILE_SIZE, QUALITY_LEVELS
from utils import safe_edit_message, safe_send_message

async def download_with_quality(context, status_message, url, download_mode, quality, quality_levels):
    """Helper function to download with specific quality"""
    current_file = None
    try:
        logger.info(f"Starting download with quality: {quality['quality_name']}")
        
        base_opts = {
            'format': quality['format'] if download_mode == 'video' else 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'outtmpl': str(DOWNLOADS_DIR / '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'socket_timeout': 30,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }
        
        if download_mode == 'audio':
            base_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        logger.info(f"Starting download with format: {base_opts['format']}")
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise Exception("Failed to download video")
            
            current_file = Path(ydl.prepare_filename(info))
            if download_mode == 'audio':
                current_file = current_file.with_suffix('.mp3')
                
            if not current_file.exists():
                raise Exception("File not found after download")
            
            logger.info(f"Successfully downloaded file: {current_file}")
            file_size = current_file.stat().st_size
            size_mb = round(file_size / (1024 * 1024), 1)
            logger.info(f"File size: {size_mb}MB")
            
            if file_size <= MAX_FILE_SIZE:
                logger.info("File size is within limits, sending...")
                await safe_edit_message(status_message, 'שולח את הקובץ... 📤')
                
                try:
                    with open(current_file, 'rb') as f:
                        if download_mode == 'video':
                            await status_message.reply_video(
                                video=f,
                                caption=current_file.stem,
                                duration=info.get('duration'),
                                width=info.get('width', 0),
                                height=info.get('height', 0),
                                supports_streaming=True,
                                read_timeout=60,
                                write_timeout=60,
                                connect_timeout=60,
                                pool_timeout=60
                            )
                        else:
                            await status_message.reply_audio(
                                audio=f,
                                title=current_file.stem,
                                performer='YouTube Audio',
                                duration=info.get('duration'),
                                read_timeout=60,
                                write_timeout=60,
                                connect_timeout=60,
                                pool_timeout=60
                            )
                    
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
                current_quality_index = context.user_data.get('current_quality_index', 0)
                logger.info(f"File too large ({size_mb}MB), current quality index: {current_quality_index}")
                
                if current_quality_index + 1 < len(quality_levels):
                    next_quality = quality_levels[current_quality_index + 1]
                    logger.info(f"Trying next quality: {next_quality['quality_name']}")
                    
                    context.user_data['current_quality_index'] = current_quality_index + 1
                    status_msg = (
                        f'הקובץ גדול מדי ({size_mb}MB), '
                        f'מנסה להוריד ב{next_quality["quality_name"]}...'
                    )
                    await safe_edit_message(status_message, status_msg)
                    
                    if current_file and current_file.exists():
                        logger.info(f"Cleaning up file before next attempt: {current_file}")
                        current_file.unlink()
                    
                    await download_with_quality(
                        context, 
                        status_message, 
                        url, 
                        download_mode, 
                        next_quality, 
                        quality_levels
                    )
                else:
                    logger.info("No more quality levels to try")
                    await safe_edit_message(
                        status_message,
                        f'הקובץ גדול מדי לשליחה ג�� באיכות הנמוכה ביותר ({size_mb}MB). '
                        'נסה סרטון קצר יותר.'
                    )
    
    except Exception as e:
        logger.error(f"Error in download_with_quality: {str(e)}")
        error_msg = str(e)
        if "Got error: " in error_msg:
            error_msg = "בעיית חיבור בהורדה. אנא נסה שוב."
        await safe_edit_message(status_message, f'אופס! משהו השתבש: {error_msg}')
    
    finally:
        if current_file and current_file.exists():
            logger.info(f"Cleaning up file in finally block: {current_file}")
            try:
                current_file.unlink()
            except Exception as e:
                logger.error(f"Error cleaning up file: {str(e)}") 
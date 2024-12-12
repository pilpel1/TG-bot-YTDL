import re
import asyncio
import telegram
from logger_setup import logger

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
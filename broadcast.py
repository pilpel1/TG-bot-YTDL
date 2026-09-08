"""שידור הודעה לכל הצ'אטים המוכרים — אדמין בלבד."""
import asyncio
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
import config
from logger_setup import logger
from user_settings import list_known_chat_ids

BROADCAST_DELAY_SECONDS = 0.05


def is_admin(user_id) -> bool:
    try:
        return int(user_id) in config.ADMIN_USER_IDS
    except (TypeError, ValueError):
        return False


def list_broadcast_targets(exclude_chat_id=None):
    """chat_ids לשידור, בלי הצ'אט של השולח."""
    skip = None
    if exclude_chat_id is not None:
        try:
            skip = str(int(exclude_chat_id))
        except (TypeError, ValueError):
            skip = str(exclude_chat_id)
    targets = []
    for chat_id in list_known_chat_ids():
        if skip is not None and str(chat_id) == skip:
            continue
        try:
            targets.append(int(chat_id))
        except (TypeError, ValueError):
            continue
    return targets


async def copy_broadcast_message(bot, target_chat_id, from_chat_id, message_id):
    """מעתיק הודעה לצ'אט אחד. מחזיר 'ok' / 'blocked' / 'failed'."""
    try:
        await bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
        )
        return 'ok'
    except Forbidden:
        return 'blocked'
    except RetryAfter as e:
        await asyncio.sleep(float(e.retry_after) + 0.1)
        try:
            await bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            return 'ok'
        except Exception as retry_error:
            logger.warning(f"Broadcast retry failed for {target_chat_id}: {retry_error}")
            return 'failed'
    except (BadRequest, TimedOut) as e:
        logger.warning(f"Broadcast skipped for {target_chat_id}: {e}")
        return 'failed'
    except Exception as e:
        logger.warning(f"Broadcast error for {target_chat_id}: {e}")
        return 'failed'


async def run_broadcast(bot, from_chat_id, message_id, targets, on_progress=None):
    """שולח copy_message לכל יעד. on_progress(sent, blocked, failed, total) אופציונלי."""
    sent = 0
    blocked = 0
    failed = 0
    total = len(targets)
    for index, target in enumerate(targets, start=1):
        result = await copy_broadcast_message(bot, target, from_chat_id, message_id)
        if result == 'ok':
            sent += 1
        elif result == 'blocked':
            blocked += 1
        else:
            failed += 1
        if on_progress and (index == total or index % 10 == 0):
            await on_progress(sent, blocked, failed, total)
        if index < total:
            await asyncio.sleep(BROADCAST_DELAY_SECONDS)
    return sent, blocked, failed

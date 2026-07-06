import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from download_queue import DownloadQueue


def make_status_message(chat_id=111):
    message = MagicMock()
    message.chat_id = chat_id
    message.edit_text = AsyncMock()
    return message


@pytest_asyncio.fixture
async def queue():
    """תור עם worker פעיל, שמנוקה (worker מבוטל) בסוף כל טסט - בלי זה
    ה-worker_task נשאר תלוי ברקע אחרי סגירת ה-event loop של הטסט."""
    download_queue = DownloadQueue()
    download_queue.start()
    yield download_queue
    await download_queue.stop()


@pytest.mark.asyncio
async def test_job_runs_immediately_when_queue_is_empty(queue):
    ran = asyncio.Event()

    async def job():
        ran.set()

    status_message = make_status_message()
    await queue.enqueue(chat_id=1, status_message=status_message, coro_factory=job)

    await asyncio.wait_for(ran.wait(), timeout=1)
    # אין המתנה בתור - אין סיבה לעדכן הודעת "מקום בתור"
    status_message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_second_job_waits_and_shows_queue_position(queue):
    first_job_started = asyncio.Event()
    release_first_job = asyncio.Event()

    async def first_job():
        first_job_started.set()
        await release_first_job.wait()

    second_job_ran = asyncio.Event()

    async def second_job():
        second_job_ran.set()

    status_message_1 = make_status_message(chat_id=1)
    status_message_2 = make_status_message(chat_id=2)

    await queue.enqueue(chat_id=1, status_message=status_message_1, coro_factory=first_job)
    await asyncio.wait_for(first_job_started.wait(), timeout=1)

    await queue.enqueue(chat_id=2, status_message=status_message_2, coro_factory=second_job)

    # הג'וב השני עדיין ממתין (הראשון עסוק) - צריך לקבל הודעת מיקום בתור מיד
    status_message_2.edit_text.assert_called_once()
    assert 'התווסף לתור' in status_message_2.edit_text.call_args[0][0]
    assert 'מיקומך: 2/2' in status_message_2.edit_text.call_args[0][0]
    assert not second_job_ran.is_set()

    release_first_job.set()
    await asyncio.wait_for(second_job_ran.wait(), timeout=1)


@pytest.mark.asyncio
async def test_cancel_prevents_queued_job_from_running(queue):
    first_job_started = asyncio.Event()
    release_first_job = asyncio.Event()

    async def first_job():
        first_job_started.set()
        await release_first_job.wait()

    second_job_ran = asyncio.Event()

    async def second_job():
        second_job_ran.set()

    status_message_1 = make_status_message(chat_id=1)
    status_message_2 = make_status_message(chat_id=2)

    await queue.enqueue(chat_id=1, status_message=status_message_1, coro_factory=first_job)
    await asyncio.wait_for(first_job_started.wait(), timeout=1)

    job_id_2 = await queue.enqueue(chat_id=2, status_message=status_message_2, coro_factory=second_job)
    assert queue.cancel(job_id_2) is True

    release_first_job.set()
    await asyncio.sleep(0.2)
    assert not second_job_ran.is_set()


@pytest.mark.asyncio
async def test_cancel_stops_currently_running_job(queue):
    job_started = asyncio.Event()
    job_cancelled = asyncio.Event()

    async def long_job():
        job_started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            job_cancelled.set()
            raise

    status_message = make_status_message()
    job_id = await queue.enqueue(chat_id=1, status_message=status_message, coro_factory=long_job)
    await asyncio.wait_for(job_started.wait(), timeout=1)

    assert queue.cancel(job_id) is True
    await asyncio.wait_for(job_cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_eta_decreases_as_running_job_progresses(queue):
    """ה-ETA חייב לרדת עם הזמן בזמן שהג'וב שלפניך רץ, ולא להישאר תקוע על
    אותו מספר (זה בדיוק הבאג שדווח - הודעה שלא מתעדכנת בפועל)."""
    release_first_job = asyncio.Event()
    first_job_started = asyncio.Event()

    async def first_job():
        first_job_started.set()
        await release_first_job.wait()

    async def second_job():
        pass

    status_message_1 = make_status_message(chat_id=1)
    status_message_2 = make_status_message(chat_id=2)

    await queue.enqueue(chat_id=1, status_message=status_message_1, coro_factory=first_job)
    await asyncio.wait_for(first_job_started.wait(), timeout=1)

    job_id_2 = await queue.enqueue(chat_id=2, status_message=status_message_2, coro_factory=second_job)

    eta_before = queue._estimated_seconds_remaining(job_id_2)
    await asyncio.sleep(1.5)
    eta_after = queue._estimated_seconds_remaining(job_id_2)

    assert eta_after <= eta_before

    release_first_job.set()


@pytest.mark.asyncio
async def test_heavier_job_shows_larger_eta_for_jobs_behind_it(queue):
    """משקל (למשל פלייליסט של 20 סרטונים) חייב להשפיע על הערכת הזמן -
    לא לערבב סרטון בודד ופלייליסט שלם באותו ממוצע."""
    release_first_job = asyncio.Event()
    first_job_started = asyncio.Event()

    async def heavy_first_job():
        first_job_started.set()
        await release_first_job.wait()

    async def second_job():
        pass

    status_message_1 = make_status_message(chat_id=1)
    status_message_2 = make_status_message(chat_id=2)

    await queue.enqueue(chat_id=1, status_message=status_message_1, coro_factory=heavy_first_job, weight=20)
    await asyncio.wait_for(first_job_started.wait(), timeout=1)

    job_id_2 = await queue.enqueue(chat_id=2, status_message=status_message_2, coro_factory=second_job)

    eta = queue._estimated_seconds_remaining(job_id_2)
    assert eta > 100  # 20 יחידות * ~12 שניות ברירת מחדל ליחידה

    release_first_job.set()


@pytest.mark.asyncio
async def test_jobs_run_one_at_a_time_not_concurrently(queue):
    """מוודא שהתור באמת סדרתי - ג'וב שני לא מתחיל לפני שהראשון הסתיים,
    כדי לא להעמיס על שרת חלש."""
    execution_order = []
    first_job_started = asyncio.Event()
    release_first_job = asyncio.Event()

    async def first_job():
        first_job_started.set()
        await release_first_job.wait()
        execution_order.append('first_done')

    async def second_job():
        execution_order.append('second_started')

    status_message_1 = make_status_message(chat_id=1)
    status_message_2 = make_status_message(chat_id=2)

    await queue.enqueue(chat_id=1, status_message=status_message_1, coro_factory=first_job)
    await asyncio.wait_for(first_job_started.wait(), timeout=1)
    await queue.enqueue(chat_id=2, status_message=status_message_2, coro_factory=second_job)

    await asyncio.sleep(0.1)
    assert execution_order == []  # השני עוד לא רץ כי הראשון תפוס

    release_first_job.set()
    await asyncio.sleep(0.1)
    assert execution_order == ['first_done', 'second_started']


@pytest.mark.asyncio
async def test_stop_cancels_worker_task_cleanly(queue):
    """זו בדיוק הבעיה שגרמה ל-'Task was destroyed but it is pending!'
    בסגירת הבוט עם Ctrl+C - צריך לוודא ש-stop() באמת מסיים את הטאסק
    (ולא רק מבקש cancel ומשאיר אותו תלוי)."""
    worker_task = queue._worker_task
    assert worker_task is not None
    assert not worker_task.done()

    await queue.stop()

    assert worker_task.done()
    assert queue._worker_task is None


@pytest.mark.asyncio
async def test_stop_is_safe_when_worker_never_started():
    never_started_queue = DownloadQueue()
    await never_started_queue.stop()  # לא אמור לזרוק שום דבר

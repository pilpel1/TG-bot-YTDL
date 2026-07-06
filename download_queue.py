import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

from logger_setup import logger

# כל כמה שניות מתעדכנת הודעת "מיקום בתור" למי שממתין
QUEUE_POSITION_UPDATE_INTERVAL_SECONDS = 5

# הערכת זמן ברירת מחדל ל"יחידת עבודה" אחת (סרטון בודד) עד שיש מספיק
# היסטוריה בפועל (ממוצע נגלגל). לפלייליסט משקל = מספר הסרטונים בו, כדי
# שהערכת הזמן לא תתבלבל בין ג'וב של סרטון בודד לג'וב של פלייליסט שלם.
DEFAULT_SECONDS_PER_UNIT = 12

# רצפת תצוגה - לא מציגים "0 שניות" (לא מדויק ומבלבל), אלא מספר קטן שמסמן
# "כמעט מוכן" בלי להתחייב למספר מדויק.
MIN_DISPLAYED_ETA_SECONDS = 5


class CancellationToken:
    """דגל ביטול פשוט המשותף בין ה-handler שמכין את ההורדה (בונה את
    coro_factory), ה-DownloadQueue, ובתוך download_manager עצמו (נבדק
    מתוך progress_hook של yt-dlp). לא צריך threading.Event - כל הצדדים
    רצים על אותו thread יחיד של ה-event loop, כולל ה-progress_hook
    הסינכרוני של yt-dlp שנקרא מתוך אותו task."""

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


@dataclass
class QueuedJob:
    job_id: str
    chat_id: int
    status_message: object
    coro_factory: Callable[[], Awaitable]
    weight: int = 1
    cancel_token: CancellationToken = field(default_factory=CancellationToken)
    task: Optional[asyncio.Task] = None
    position_updater: Optional[asyncio.Task] = None
    enqueued_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None


class DownloadQueue:
    """תור הורדות סדרתי (worker יחיד) - ג'וב אחד רץ בכל זמן נתון.

    השרת חלש - במקום להריץ הורדות במקביל (concurrent_updates=True) שיעמיסו
    יחד על הדיסק/רשת/ffmpeg, כל בקשה נכנסת לתור ומחכה בתורה. חשוב לא פחות:
    ה-handler שמכניס ג'וב לתור *לא* מחכה לסיום שלו (enqueue מחזיר מיד) -
    כך ש-python-telegram-bot (שמעבד עדכונים ברצף, concurrent_updates=False
    כברירת מחדל) חופשי להמשיך לטפל בהודעות של משתמשים אחרים תוך כדי שהורדה
    ארוכה רצה ברקע דרך ה-worker.

    הערכת הזמן מבוססת על "משקל" (weight) לכל ג'וב - סרטון בודד=1, פלייליסט
    של N סרטונים=N - וממוצע נגלגל של שניות-ליחידה (לא שניות-לג'וב, כי ג'וב
    של סרטון בודד וג'וב של פלייליסט שלם הם בסדרי גודל שונים לגמרי ולא ניתן
    לערבב אותם בממוצע אחד). בנוסף, לג'וב שכבר רץ בפועל (started_at קיים)
    מחשבים "כמה נשאר" לפי הזמן שכבר חלף מול המשך הצפוי - כדי שהתצוגה תרד
    עם הזמן במקום להישאר תקועה על אותו מספר עד שהג'וב שלפניך מסתיים.
    """

    def __init__(self):
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._jobs: dict[str, QueuedJob] = {}
        self._avg_seconds_per_unit = DEFAULT_SECONDS_PER_UNIT
        self._worker_task: Optional[asyncio.Task] = None
        self._job_counter = 0

    def start(self):
        """מפעיל את ה-worker. יש לקרוא פעם אחת, אחרי שיש event loop רץ."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Download queue worker started")

    async def stop(self):
        """עוצר את ה-worker בצורה מסודרת - חובה לקרוא לפני שה-event loop
        נסגר (למשל ב-post_stop של python-telegram-bot). בלי זה הטאסק
        נשאר "תלוי" כש-run_polling סוגר את הלולאה בכיבוי (Ctrl+C), וגורם
        ל-'Task was destroyed but it is pending!' בלוגים."""
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    async def enqueue(self, chat_id, status_message, coro_factory, weight: int = 1,
                       cancel_token: Optional[CancellationToken] = None) -> str:
        """מכניס ג'וב לתור ומחזיר מיד (לא מחכה לביצוע בפועל).

        coro_factory: פונקציה בלי ארגומנטים שמחזירה coroutine (לא coroutine
        עצמו!) כדי שהריצה בפועל תתחיל רק כשה-worker מגיע אליו, לא בזמן ההכנסה.

        weight: "יחידות עבודה" משוערות בג'וב הזה (1 לסרטון בודד, N לפלייליסט
        של N סרטונים) - משמש רק להערכת זמן, לא משפיע על סדר העיבוד (FIFO).

        cancel_token: אותו טוקן שהמזמין (coro_factory) כבר מעביר פנימה
        ל-download_with_quality/download_playlist כ-should_cancel. אם לא
        סופק, נוצר טוקן חדש - אז cancel() עדיין "עובד" אך בלי אפקט בפועל
        על ההורדה עצמה (רק מסמן/מסיר מהתור).
        """
        self._job_counter += 1
        job_id = f"{chat_id}-{self._job_counter}-{int(time.time() * 1000)}"
        job = QueuedJob(
            job_id=job_id,
            chat_id=chat_id,
            status_message=status_message,
            coro_factory=coro_factory,
            weight=max(1, weight),
            cancel_token=cancel_token or CancellationToken(),
        )
        self._jobs[job_id] = job

        await self._queue.put(job_id)

        position = self._position_ahead(job_id)
        if position > 0:
            job.position_updater = asyncio.create_task(self._position_update_loop(job_id))
            await self._render_position_message(job_id)

        return job_id

    def cancel(self, job_id: str) -> bool:
        """מבטל ג'וב - גם אם עדיין ממתין בתור וגם אם כבר רץ.

        לג'וב שכבר רץ בפועל: מסמנים את cancel_token (נבדק מתוך progress_hook
        סינכרוני בתוך yt-dlp - זה מה שבאמת עוצר הורדה שנמצאת באמצע קובץ,
        כי ydl.download() חוסם את ה-event loop ואין נקודת await לתפוס שם
        Task.cancel()) וגם קוראים ל-task.cancel() (תופס נקודות await
        אמיתיות, למשל בין סרטון לסרטון בפלייליסט)."""
        job = self._jobs.get(job_id)
        if not job:
            return False

        job.cancel_token.cancel()

        if job.task and not job.task.done():
            job.task.cancel()
            return True

        if job.position_updater:
            job.position_updater.cancel()
        self._jobs.pop(job_id, None)
        return True

    def get_job_id_for_chat(self, chat_id) -> Optional[str]:
        """מוצא ג'וב פעיל/ממתין עבור chat_id נתון - משמש את פקודת /stop."""
        for job_id, job in self._jobs.items():
            if job.chat_id == chat_id:
                return job_id
        return None

    def _position_ahead(self, job_id: str) -> int:
        """כמה ג'ובים לפני זה בתור (0 = הבא בתור / רץ עכשיו).
        מסתמך על כך ש-dict שומר סדר הכנסה, שתואם לסדר ה-FIFO של התור."""
        for index, jid in enumerate(self._jobs):
            if jid == job_id:
                return index
        return len(self._jobs)

    def _estimated_seconds_remaining(self, job_id: str) -> int:
        """מעריך כמה שניות נשארו עד שהג'וב הזה יתחיל לרוץ.
        לג'וב שכבר רץ (started_at קיים - יכול להיות לכל היותר אחד, כי יש
        worker יחיד) מחשבים כמה נשאר לו לפי הזמן שכבר חלף; לג'ובים שעדיין
        לא התחילו מעריכים לפי המשקל שלהם."""
        remaining = 0.0
        for jid, job in self._jobs.items():
            if jid == job_id:
                break
            if job.started_at is not None:
                expected_total = job.weight * self._avg_seconds_per_unit
                elapsed = time.monotonic() - job.started_at
                remaining += max(0.0, expected_total - elapsed)
            else:
                remaining += job.weight * self._avg_seconds_per_unit
        return max(MIN_DISPLAYED_ETA_SECONDS, int(remaining))

    async def _render_position_message(self, job_id: str):
        job = self._jobs.get(job_id)
        if not job:
            return

        position = self._position_ahead(job_id)
        if position <= 0:
            return

        total_jobs = len(self._jobs)
        eta_seconds = self._estimated_seconds_remaining(job_id)
        try:
            await job.status_message.edit_text(
                f'התווסף לתור 🕐 מיקומך: {position + 1}/{total_jobs}\n'
                f'זמן המתנה משוער: כ-{eta_seconds} שניות'
            )
        except Exception as e:
            logger.warning(f"Could not update queue position message: {e}")

    async def _position_update_loop(self, job_id: str):
        try:
            while True:
                await asyncio.sleep(QUEUE_POSITION_UPDATE_INTERVAL_SECONDS)
                job = self._jobs.get(job_id)
                if not job:
                    return

                position = self._position_ahead(job_id)
                if position <= 0:
                    return

                await self._render_position_message(job_id)
        except asyncio.CancelledError:
            return

    async def _worker_loop(self):
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if job is None:
                self._queue.task_done()
                continue

            if job.position_updater:
                job.position_updater.cancel()
                job.position_updater = None

            job.started_at = time.monotonic()
            # רץ כ-task נפרד מהלולאה של ה-worker עצמו - כך ביטול הג'וב
            # (job.task.cancel()) לא הורג את ה-worker, רק את הג'וב הנוכחי.
            job.task = asyncio.create_task(job.coro_factory())

            try:
                await job.task
            except asyncio.CancelledError:
                logger.info(f"Job {job_id} was cancelled")
                # אם הביטול הזה הוא בעצם ביטול של ה-worker task עצמו (לא רק
                # של הג'וב הבודד) - צריך להמשיך להתפשט ולסיים את הלולאה,
                # אחרת ה-worker "בולע" את הביטול שלו ונשאר תקוע לנצח.
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    raise
            except Exception as e:
                logger.error(f"Job {job_id} raised an error: {e}")
            finally:
                duration = time.monotonic() - job.started_at
                seconds_per_unit = duration / job.weight
                self._avg_seconds_per_unit = (self._avg_seconds_per_unit + seconds_per_unit) / 2
                self._jobs.pop(job_id, None)
                self._queue.task_done()

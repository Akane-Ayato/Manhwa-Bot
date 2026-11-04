import asyncio
import random
import shutil
import string
import time
from threading import RLock, Timer
from typing import Dict, Optional, Tuple

import pyrogram
import pyrogram.errors
from loguru import logger
from pyrogram.errors import FloodWait

from bot import Bot, Vars
from .db import database, get_episode_number
from .img2pdf import thumbnali_images, download_and_convert_images
from .progress import Progress, schedule_push

from os import path as ospath


def igrone_error(func, sync=False):
    """Wrap `func` so that any error is swallowed and None is returned.

    Pyrogram's control-flow exceptions (ContinuePropagation / StopPropagation)
    are deliberately re-raised: they derive from Exception, and swallowing them
    made a decorated handler silently end dispatch for every other handler.
    """
    async def wrapper(*args, **kwargs):
        try:
            if sync:
                return await asyncio.to_thread(func, *args, **kwargs)
            return await func(*args, **kwargs)
        except (pyrogram.ContinuePropagation, pyrogram.StopPropagation):
            raise
        except Exception as err:
            logger.debug(f"igrone_error: {getattr(func, '__name__', func)} -> {type(err).__name__}: {err}")
            return None

    return wrapper


def retry_on_flood(func, max_retries: int = 5):
    """Retry a pyrogram call when Telegram answers FloodWait.

    (The original slept twice per flood - e.g. 2x(wait+3) - and retried forever.)
    Every other error is re-raised immediately for the caller to handle.
    """
    async def wrapper(*args, **kwargs):
        attempt = 0
        while True:
            try:
                return await func(*args, **kwargs)
            except FloodWait as e:
                attempt += 1
                if attempt > max_retries:
                    raise
                wait = int(e.value) + 1
                logger.warning(f"FloodWait: waiting {wait}s (attempt {attempt}/{max_retries})")
                await asyncio.sleep(wait)
            except (
                ValueError,
                pyrogram.errors.QueryIdInvalid,
                pyrogram.errors.MessageNotModified,
                pyrogram.errors.BadRequest,
                pyrogram.ContinuePropagation,
                pyrogram.StopPropagation,
            ):
                raise
            except Exception as e:
                logger.warning(f"{getattr(func, '__name__', func)} failed: {type(e).__name__}: {e}")
                raise

    return wrapper


class MangaCard:
    __slots__ = ('url', 'title', 'poster', 'msg', 'chapters', 'webs', 'data')

    def __init__(
        self, 
        webs=None, url: str = "", 
        title: str = "", poster: str = "", 
        msg: str = "",  chapters: Optional[list] = None,
        data: Optional[dict] = None
    ):
        self.url = url
        self.title = title
        self.poster = poster
        self.msg = msg
        self.chapters = [] if chapters is None else chapters
        self.webs = webs
        self.data = {} if data is None else data

    def __repr__(self):
        return f"MangaCard({self.title})"

    def load_to_class(self, data: dict) -> 'MangaCard':
        slots = self.__slots__
        for key, val in data.items():
            if key in slots:
                setattr(self, key, val)
            else:
                self.data[key] = val
        return self


    def load_to_dict(self) -> dict:
        result = {}
        slots = self.__slots__

        for i in range(len(slots)):
            key = slots[i]
            if key == "data":
                result.update(self.data)
            else:
                result[key] = getattr(self, key)
        return result

    def update_dict(self, data: dict) -> None:
        slots = self.__slots__
        for key, val in data.items():
            if key in slots:
                setattr(self, key, val)
            else:
                self.data[key] = val

    @classmethod
    def from_dict(cls, data: dict) -> 'MangaCard':
        obj = cls.__new__(cls)

        obj.url = ""
        obj.title = ""
        obj.poster = ""
        obj.msg = ""
        obj.chapters = []
        obj.webs = None
        obj.data = {}

        obj.load_to_class(data)
        return obj


class Subscribes:
  """A class to manage user-specific subscriptions."""
  __slots__ = ('user_id', "manga_url", "webs", "lastest_chapter", "manga_title")

  def __init__(self, webs: str, manga_url: str, lastest_chapter: str, manga_title: str):
    self.manga_url: str = manga_url
    self.manga_title: str = manga_title
    self.webs: str = webs
    self.lastest_chapter: str = lastest_chapter

  def load_to_dict(self):
     return {"url": self.manga_url, "title": self.manga_title, "lastest_chapter": self.lastest_chapter}


def clean(txt, length=-1):
    remove_char = [
        "_", "&", ";", ":", "'", "|", "*", "?", ">", "<", "`", 
        "!", "@", "#", "$", "%", "^", "~", "+", "=", "/", 
        "\\", "\n",
    ]
    translator = txt.maketrans("", "", "".join(remove_char))
    txt = txt.translate(translator)

    txt = txt.replace("None", "")
    txt = txt.replace(".jpg", "")

    return txt[:length] if length != -1 else txt



def _zfill_width(regex) -> int:
    try:
        return max(int(regex), 0)
    except (TypeError, ValueError):
        return 0


def get_file_name(data: list, setting: Optional[dict] = None):
    setting = setting or {}
    regex = _zfill_width(setting.get('regex', None))

    flen = setting.get('file_name_len', "30")
    try:
        flen = int(flen)
    except Exception:
        flen = 30

    if len(data) > 1:
        episode_number1 = str(get_episode_number(data[0].get("title", "None")))
        if not episode_number1 or (episode_number1 == "None"):
            episode_number1 = clean(data[0].get("title", "None"))
        else:
            episode_number1 = episode_number1.zfill(regex) if regex else episode_number1

        episode_number2 = str(get_episode_number(data[-1].get("title", "None")))
        if not episode_number2 or (episode_number2 == "None"):
            episode_number2 = clean(data[-1].get("title", "None"))
        else:
            episode_number2 = episode_number2.zfill(regex) if regex else episode_number2

        episode_number = f"{episode_number1} - {episode_number2}"
    else:
        episode_number = str(get_episode_number(data[0].get("title", "None")))
        if (episode_number == "None") or not episode_number:
            episode_number = clean(data[0].get("title", "None"))
        else:
            episode_number = episode_number.zfill(regex) if regex else episode_number

    orginal_manga_title = data[0].get("manga_title", "")
    manga_title = clean(orginal_manga_title, flen)

    return orginal_manga_title, manga_title, episode_number


async def process_thumbnail_pdf(thumb_path):
    import os
    from PIL import Image, ImageOps

    if not thumb_path or not os.path.exists(thumb_path):
        return None

    try:
        img = await asyncio.to_thread(Image.open, thumb_path)
        img = await asyncio.to_thread(lambda: img.convert("RGB"))

        img = await asyncio.to_thread(lambda: ImageOps.contain(img, (320, 320), Image.LANCZOS))


        img = await asyncio.to_thread(lambda: ImageOps.pad(img, (320, 320), color=(0, 0, 0)))


        await asyncio.to_thread(img.save, thumb_path, "JPEG", quality=95)

    except Exception:
        pass

    return thumb_path

async def load_images_(u_id, p, b_url=None, p_fn=None, md=None):
    import base64
    import os

    s = {}
    us = await database.get_settings(u_id)

    md = md or f"Process/{u_id}"
    os.makedirs(md, exist_ok=True)

    prs = [
        ("banner1_file_path", us.get("banner1", None)), 
        ("banner2_file_path", us.get("banner2", None)), 
        ("thumb_file_name", us.get("thumb", None))
    ]

    def s64(b6, fp):
        try:
            if b6.startswith("data:"):
                b6 = b6.split(",", 1)[1]

            d = base64.b64decode(b6)
            with open(fp, "wb") as f:
                f.write(d)

            return fp
        except Exception:
            return None

    for k, v in prs:
        t = None
        fp = f"{md}/{k}.jpg"
        if ospath.exists(fp):
            t = fp
            s[k] = t

        elif v and v.startswith("http"):
            t = await igrone_error(thumbnali_images)(image_url=v, download_dir=md, file_name=k)
            t = await process_thumbnail_pdf(thumb_path=t)
            s[k] = t

        elif v and v.startswith("data:image"):
            t = s64(v, fp)
            s[k] = t

        elif v and (v.startswith("/9j") or v.startswith("iVBOR") or len(v) > 500):
            try:
                t = s64(v, fp)
                s[k] = t
            except Exception:
                t = await igrone_error(Bot.download_media)(v, file_name=fp)
                t = await process_thumbnail_pdf(thumb_path=t)
                s[k] = t

        elif v == "constant":
            t = await igrone_error(thumbnali_images)(image_url=p, download_dir=md, file_name=p_fn, base_url=b_url)
            t = await process_thumbnail_pdf(thumb_path=t)

            s[k] = t
        elif v:
            t = await igrone_error(Bot.download_media)(v, file_name=fp)
            t = await process_thumbnail_pdf(thumb_path=t)
            s[k] = t

    return s




class TaskCard:
    """ A class to manage user-specific tasks. """
    def __init__(
        self, webs, sts, picturesList,
        user_id, chat_id, priority,
        tasks_id=None, data_list: Optional[list] = None,
        update_mode: bool = False,
        settings: Optional[dict] = None,
        kind: str = "user",
    ):
        if not data_list:
            raise ValueError("TaskCard needs at least one chapter in data_list")

        self.picturesList = picturesList or []
        self.poster: str = data_list[0].get("poster", "") # data

        self.webs = webs
        self.sts = sts
        self.setting = settings if settings is not None else {}
        self.orginal_manga_title, self.manga_title, self.episode_number = get_file_name(data_list, self.setting)

        if len(data_list) == 1:
            self.url = data_list[0].get("url", "") # data
        else:
            self.url = f"{data_list[0].get('url', '')} - {data_list[-1].get('url', '')}"

        self.tasks_id = tasks_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.priority = priority
        self.update_mode = update_mode

        # --- v2: progress bars + channel-mapping ("auto") tasks -----------
        self.kind = kind                  # "user" (normal) or "auto" (posts to a mapped channel)
        self.progress = Progress()
        self.map_id = None                # channel_maps id for auto tasks
        self.chapter_key = None           # chapter number the task posts
        self.owner_id = None              # admin who owns the mapping (settings + error reports)
        self.error_chat = None            # where errors go (auto tasks: the owner, never the channel)
        self.target_title = None          # shown in the progress message
        self.on_success = None            # async (card, messages) -> None
        self.on_failure = None            # async (card, reason) -> None
        self.fail_reason = None
        self._failure_sent = False
        self.runner = None             # asyncio task running this card (set by the worker)
        self.cancel_requested = False
        self.report = {}               # filled by the worker: what was really applied

        # Always defined, so close()/cworker never hit AttributeError
        self.processsing = None
        self.main_dir = f"Process/{tasks_id}" if tasks_id else None
        self.download_dir = None
        self.compressed_dir = None

    def run_process(self) -> None:
        """Start downloading the pictures in the background (idempotent)."""
        if not self.tasks_id or not self.webs:
            return
        if self.processsing is not None:
            return

        cs = getattr(self.webs, "cs", False)
        self.main_dir = f"Process/{self.tasks_id}"
        self.download_dir = f"{self.main_dir}/pictures"
        self.compressed_dir = f"{self.main_dir}/compress"

        self.processsing = asyncio.create_task(
            download_and_convert_images(
                self.picturesList, self.download_dir,
                self.webs.url, cs=cs,
                on_progress=self._on_download_progress,
            )
        )

    def _on_download_progress(self, done: int, total: int) -> None:
        if self.progress.stage != "Downloading":
            self.progress.set_stage("Downloading", total=total, unit="pages")
        self.progress.update(done, total)
        schedule_push(self)

    async def close(self) -> None:
        if self.processsing is not None:
            self.processsing.cancel()

        if self.main_dir:
            shutil.rmtree(self.main_dir, ignore_errors=True)
        if self.sts:
            await igrone_error(self.sts.delete)()

    async def get_banner(self) -> dict:
        """Banner/thumbnail files.  Channel (auto) tasks have the CHANNEL id as user_id, so their
        settings must come from the mapping's owner, and their files go to a private folder that is
        deleted together with the task (several channel tasks of one owner run at the same time)."""
        if self.kind == "auto" and self.owner_id:
            return await load_images_(
                self.owner_id, self.poster, self.webs.url, self.manga_title,
                md=f"Process/{self.tasks_id}/assets",
            )
        return await load_images_(
            self.user_id,
            self.poster,
            self.webs.url,
            self.manga_title
        )


def episode_sort_key(ep) -> tuple:
    """Sort key for episode numbers: 3, "3", "10.5", "10 - 12" (first number wins);
    unknown/None values go last."""
    if ep is None:
        return (2, 0.0, "")
    text = str(ep).strip().lower()
    if text in ("", "none"):
        return (2, 0.0, "")
    first = text.split("-")[0].strip()
    try:
        return (0, float(first), "")
    except ValueError:
        return (3, 0.0, text)


class AQueue:
    """In-memory task queue.

    Rules: a user has at most ONE task running at a time (`ongoing_tasks` is
    keyed by user id); premium users (priority 1) are served before the rest;
    otherwise users are served first-come-first-served, and inside one user's
    backlog chapters go out in ascending chapter order.
    """
    __slots__ = ('storage_data', 'ongoing_tasks', 'maxsize', '_event')

    def __init__(self, maxsize: Optional[int] = None):
        self.storage_data: Dict[str, Tuple[TaskCard, bool]] = {}  # {task_id: (TaskCard, is_auto_update)}
        self.ongoing_tasks: Dict[int, TaskCard] = {}               # {user_id: TaskCard}
        self.maxsize = maxsize
        self._event: Optional[asyncio.Event] = None

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _uid(user_id) -> int:
        return int(user_id)

    def _wake(self) -> None:
        if self._event is not None:
            self._event.set()

    async def get_random_id(self) -> str:
        """Generate unique 7-char task ID"""
        chars = string.ascii_letters + string.digits + "s"
        while True:
            task_id = ''.join(random.choices(chars, k=7))
            if task_id not in self.storage_data and not any(
                t.tasks_id == task_id for t in self.ongoing_tasks.values()
            ):
                return task_id

    # -- producer ---------------------------------------------------------
    async def put(self, tasks: TaskCard, updates: bool = False) -> str:
        """Add task to queue"""

        if self.maxsize and len(self.storage_data) >= self.maxsize:
            raise asyncio.QueueFull("Queue full")

        is_auto = getattr(tasks, "kind", "user") == "auto"
        if not is_auto:  # channel ids must never become "users" (broadcasts would hit them)
            await database.ensure_user(tasks.user_id)
        tasks.tasks_id = await self.get_random_id()

        if not tasks.setting:
            tasks.setting = await database.get_settings(tasks.user_id)

        self.storage_data[tasks.tasks_id] = (tasks, updates)

        if Vars.IS_PRIVATE and not is_auto:  # auto tasks download when a worker takes them (disk)
            tasks.run_process()

        self._wake()
        return tasks.tasks_id

    # -- scheduling -------------------------------------------------------
    def get_available_tasks(self, user_id=None):
        """Next runnable (TaskCard, is_update) - optionally only for one user - or None."""
        wanted = None if user_id is None else self._uid(user_id)
        # channel uploads may use only AUTO_MAX_PARALLEL workers; the rest stay free for users
        auto_full = self.auto_running() >= getattr(Vars, "AUTO_MAX_PARALLEL", 6)

        # per user: [best priority, first arrival index, [(arrival, task, flag), ...]]
        users: Dict[int, list] = {}
        for arrival, (task, flag) in enumerate(self.storage_data.values()):
            uid = self._uid(task.user_id)
            if (wanted is not None and uid != wanted) or uid in self.ongoing_tasks:
                continue
            if auto_full and getattr(task, "kind", "user") == "auto":
                continue
            info = users.setdefault(uid, [task.priority or 0, arrival, []])
            info[0] = max(info[0], task.priority or 0)
            info[2].append((arrival, task, flag))

        if not users:
            return None

        # premium first, then whoever has waited longest
        best_user = min(users.values(), key=lambda info: (-info[0], info[1]))
        _, task, flag = min(best_user[2], key=lambda x: (episode_sort_key(x[1].episode_number), x[0]))
        return (task, flag)

    async def get(self, worker_id: int) -> Tuple[TaskCard, bool]:
        """Wait for, claim and return the next runnable task."""
        if self._event is None:
            self._event = asyncio.Event()

        while True:
            try:
                available = self.get_available_tasks()
                if available:
                    task = available[0]
                    self.ongoing_tasks[self._uid(task.user_id)] = task
                    del self.storage_data[str(task.tasks_id)]
                    return available

                self._event.clear()
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"Error in queue get: {e}")
                await asyncio.sleep(1)

    # -- cancelling -------------------------------------------------------
    async def delete_task(self, task_id: str) -> bool:
        """Cancel one *pending* task (auto-update tasks can't be cancelled by users).

        Returns True if the task id was known."""
        entry = self.storage_data.get(task_id)
        if entry is None:
            return False

        task_card, is_update = entry
        if is_update is not True:
            self.storage_data.pop(task_id, None)
            await igrone_error(task_card.close)()

        return True

    async def delete_tasks(self, user_id: int) -> int:
        """Delete all of a user's pending tasks (the running one is left alone). Returns the count."""
        uid = self._uid(user_id)
        ids = [tid for tid, (task, _) in self.storage_data.items() if self._uid(task.user_id) == uid]

        cards = []
        for tid in ids:
            entry = self.storage_data.pop(tid, None)
            if entry:
                cards.append(entry[0])

        if cards:
            await asyncio.gather(
                *(asyncio.wait_for(igrone_error(card.close)(), 20) for card in cards),
                return_exceptions=True,
            )
        return len(cards)

    async def cancel_user(self, user_id: int) -> tuple:
        """/clean: drop the user's pending tasks AND cancel the one that is running.  -> (pending, running)"""
        uid = self._uid(user_id)
        pending = await self.delete_tasks(user_id)
        running = 0
        for card in list(self.ongoing_tasks.values()):
            if getattr(card, "kind", "user") != "user" or self._uid(card.user_id) != uid:
                continue
            card.cancel_requested = True
            runner = getattr(card, "runner", None)
            if runner is not None and not runner.done():
                runner.cancel()
                running += 1
        return pending, running

    def auto_running(self) -> int:
        return sum(1 for t in self.ongoing_tasks.values() if getattr(t, "kind", "user") == "auto")

    def auto_pending(self) -> list:
        return [t for t, _ in self.storage_data.values() if getattr(t, "kind", "user") == "auto"]

    def auto_ongoing(self) -> list:
        return [t for t in self.ongoing_tasks.values() if getattr(t, "kind", "user") == "auto"]

    def has_map_chapter(self, map_id, chapter_key) -> bool:
        """True if (mapping, chapter) is already waiting or running (prevents double-queueing)."""
        for t, _ in self.storage_data.values():
            if getattr(t, "map_id", None) == map_id and getattr(t, "chapter_key", None) == chapter_key:
                return True
        return any(
            getattr(t, "map_id", None) == map_id and getattr(t, "chapter_key", None) == chapter_key
            for t in self.ongoing_tasks.values()
        )

    async def delete_map_tasks(self, map_id) -> int:
        """Drop every *pending* task of one mapping (used by pause/remove)."""
        ids = [tid for tid, (t, _) in self.storage_data.items() if getattr(t, "map_id", None) == map_id]
        cards = []
        for tid in ids:
            entry = self.storage_data.pop(tid, None)
            if entry:
                cards.append(entry[0])
        for card in cards:
            await igrone_error(card.close)()
        return len(cards)

    # -- info -------------------------------------------------------------
    def get_count(self, user_id: int = 0) -> int:
        """user_id == 0: number of distinct users with pending/running work;
        otherwise that user's pending + running task count."""
        try:
            if user_id == 0:
                users = {self._uid(t.user_id) for t, _ in self.storage_data.values()}
                users.update(self._uid(t.user_id) for t in self.ongoing_tasks.values())
                return len(users)

            uid = self._uid(user_id)
            running = sum(1 for t in self.ongoing_tasks.values() if self._uid(t.user_id) == uid)
            pending = sum(1 for t, _ in self.storage_data.values() if self._uid(t.user_id) == uid)
            return running + pending
        except (ValueError, TypeError, AttributeError) as e:
            logger.error(f"Error counting tasks for user {user_id}: {e}")
            return 0

    def task_exists(self, task_id: str) -> bool:
        return task_id in self.storage_data or any(
            t.tasks_id == task_id for t in self.ongoing_tasks.values()
        )

    def qsize(self) -> int:
        return len(self.storage_data)

    def empty(self) -> bool:
        return not self.storage_data

    async def task_done(self, tasks_card: TaskCard) -> bool:
        """Mark a claimed task as finished so the user's next task can start."""
        uid = self._uid(tasks_card.user_id)
        if self.ongoing_tasks.get(uid) is tasks_card:
            del self.ongoing_tasks[uid]
            self._wake()
            return True

        return False

    def get_ongoing_count(self, user_id: int) -> int:
        """Get user's ongoing task count"""
        return sum(1 for t in self.ongoing_tasks.values() if self._uid(t.user_id) == self._uid(user_id))

    def check_queue(self, user_id) -> bool:
        """True if the user still has pending tasks."""
        uid = self._uid(user_id)
        return any(self._uid(task.user_id) == uid for task, _ in list(self.storage_data.values()))


queue = AQueue()


""" Make By AI """
class TTLCache:
    """
    A dictionary-like class that automatically removes entries after a specified time.

    Features:
    - Behaves like a regular dictionary (supports get, set, delete, membership tests)
    - Each entry has its own expiration time
    - Automatic cleanup of expired entries
    - Thread-safe operations
    """

    def __init__(self, default_timeout=60, cleanup_interval=30, max_entries=None):
        """
        Initialize the TimedDict.

        Args:
            default_timeout (int): Default time in seconds after which entries expire
            cleanup_interval (int): How often to run cleanup in seconds (0 to disable)
        """
        self._dict = {}  # Main storage: key -> (value, expiry_time)
        self._max_entries = max_entries  # optional hard cap (oldest-expiring entries are dropped)
        self._default_timeout = default_timeout
        self._lock = RLock()

        # Start periodic cleanup if interval > 0
        self._cleanup_interval = cleanup_interval
        if cleanup_interval > 0:
            self._start_cleanup_timer()

    def _start_cleanup_timer(self):
        """Start the periodic cleanup timer."""
        self._cleanup_timer = Timer(self._cleanup_interval, self._cleanup)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _cleanup(self):
        """Remove all expired entries."""
        current_time = time.time()
        with self._lock:
            # Collect keys to delete
            keys_to_delete = [
                key for key, (_, expiry) in self._dict.items()
                if expiry <= current_time
            ]
            # Delete expired keys
            for key in keys_to_delete:
                del self._dict[key]

        # Restart timer if still needed
        if self._cleanup_interval > 0:
            self._start_cleanup_timer()

    def __getitem__(self, key):
        """Get value for key, raising KeyError if expired or not found."""
        with self._lock:
            if key not in self._dict:
                raise KeyError(key)

            value, expiry = self._dict[key]
            if time.time() > expiry:
                # Entry has expired
                del self._dict[key]
                raise KeyError(f"Key '{key}' has expired")

            return value

    def __setitem__(self, key, value):
        """Set value with default timeout."""
        self.set(key, value, self._default_timeout)

    def set(self, key, value, timeout=None):
        """
        Set a key with optional custom timeout.

        Args:
            key: The key to set
            value: The value to store
            timeout: Custom timeout in seconds (uses default_timeout if None)
        """
        expiry = time.time() + (timeout if timeout is not None else self._default_timeout)
        with self._lock:
            self._dict[key] = (value, expiry)
            if self._max_entries and len(self._dict) > self._max_entries:
                overflow = len(self._dict) - self._max_entries
                for old_key in sorted(self._dict, key=lambda k: self._dict[k][1])[:overflow]:
                    del self._dict[old_key]

    def __delitem__(self, key):
        """Delete a key."""
        with self._lock:
            del self._dict[key]

    def __contains__(self, key):
        """Check if key exists and is not expired."""
        try:
            self.__getitem__(key)
            return True
        except KeyError:
            return False

    def get(self, key, default=None):
        """Get value with default if key doesn't exist or is expired."""
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def pop(self, key, default=None):
        """
        Remove and return value for key.
        Returns default if key doesn't exist or is expired.
        """
        try:
            value = self.__getitem__(key)
            with self._lock:
                self._dict.pop(key, None)
            return value
        except KeyError:
            return default

    def keys(self):
        """Return list of non-expired keys."""
        current_time = time.time()
        with self._lock:
            # First clean up expired entries
            keys_to_delete = [
                key for key, (_, expiry) in self._dict.items()
                if expiry <= current_time
            ]
            for key in keys_to_delete:
                del self._dict[key]

            return list(self._dict.keys())

    def values(self):
        """Return list of non-expired values."""
        current_time = time.time()
        with self._lock:
            values = []
            keys_to_delete = []

            for key, (value, expiry) in self._dict.items():
                if expiry > current_time:
                    values.append(value)
                else:
                    keys_to_delete.append(key)

            # Clean up expired entries
            for key in keys_to_delete:
                del self._dict[key]

            return values

    def items(self):
        """Return list of (key, value) pairs for non-expired entries."""
        current_time = time.time()
        with self._lock:
            items = []
            keys_to_delete = []

            for key, (value, expiry) in self._dict.items():
                if expiry > current_time:
                    items.append((key, value))
                else:
                    keys_to_delete.append(key)

            # Clean up expired entries
            for key in keys_to_delete:
                del self._dict[key]

            return items

    def __len__(self):
        """Return number of non-expired entries."""
        return len(self.keys())

    def __iter__(self):
        """Iterate over non-expired keys."""
        return iter(self.keys())

    def clear(self):
        """Remove all entries."""
        with self._lock:
            self._dict.clear()

    def update(self, other_dict):
        """Update with another dictionary, using default timeout."""
        with self._lock:
            for key, value in other_dict.items():
                self[key] = value

    def setdefault(self, key, default=None):
        """
        Get value if key exists, otherwise set to default and return default.
        """
        try:
            return self.__getitem__(key)
        except KeyError:
            self[key] = default
            return default

    def get_expiry_time(self, key):
        """
        Get expiry time for a key as timestamp.
        Returns None if key doesn't exist.
        """
        with self._lock:
            if key in self._dict:
                return self._dict[key][1]
            return None

    def refresh_key(self, key, timeout=None):
        """
        Reset the expiry time for an existing key.
        Returns True if successful, False if key doesn't exist.
        """
        with self._lock:
            if key in self._dict:
                value, _ = self._dict[key]
                expiry = time.time() + (timeout if timeout is not None else self._default_timeout)
                self._dict[key] = (value, expiry)
                return True
            return False

    def __repr__(self):
        """String representation."""
        items = self.items()
        return f"TimedDict({dict(items)})"

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up."""
        self.clear()
        if hasattr(self, '_cleanup_timer'):
            self._cleanup_timer.cancel()
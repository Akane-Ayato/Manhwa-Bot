"""Auto-poster: checks every mapped series and queues new chapters for its channel.

Flow per mapping:
  scrape chapter list -> chapters never posted (ascending) -> fetch pictures ->
  TaskCard(kind="auto") in the shared queue -> worker uploads to the channel ->
  on_success: remember chapter, announce in UPDATE_CHANNEL
  on_failure: count the attempt; after RETRY_LIMIT the chapter is "failed" (and blocks the
              following chapters of that series so the channel stays in order) until
              /ch_retry or /ch_skip.

Safety nets: per-site concurrency + delay, per-site circuit breaker, a limit on how many
"new" chapters one check may queue (a scraper/site-layout change must not flood a channel).
"""
import asyncio
import random
import shutil
import time
from typing import Dict, List, Optional

from loguru import logger

from bot import Bot
from config import Vars
from . import chmap
from .announce import announce_chapter
from .base import TaskCard, queue, retry_on_flood, igrone_error
from .db import database

SCRAPE_TIMEOUT = 120          # seconds for one chapter-list request
BURST_LIMIT = 8               # more "new" chapters than this in one check => suspicious, pause + alert
SITE_FAIL_LIMIT = 5           # consecutive failures that open the site's circuit breaker
SITE_DOWN_SECONDS = 600


# ------------------------------------------------------------ site health ---
class SiteGate:
    """Concurrency/delay limiter + circuit breaker for one website."""

    def __init__(self, sf: str):
        self.sf = sf
        self.sem = asyncio.Semaphore(Vars.SITE_CONCURRENCY)
        self.fail_streak = 0
        self.down_until = 0.0
        self.last_ok = 0.0
        self.last_error = ""
        self.alerted = False

    @property
    def is_down(self) -> bool:
        return time.time() < self.down_until

    def ok(self) -> None:
        self.fail_streak, self.last_ok, self.alerted = 0, time.time(), False
        self.down_until = 0.0

    def fail(self, error: str) -> bool:
        """Register a failure; returns True when this failure just opened the breaker."""
        self.fail_streak += 1
        self.last_error = (error or "")[:200]
        if self.fail_streak >= SITE_FAIL_LIMIT:
            self.down_until = time.time() + SITE_DOWN_SECONDS
            opened = not self.alerted
            self.alerted = True
            return opened
        return False


_gates: Dict[str, SiteGate] = {}


def gate_for(sf: str) -> SiteGate:
    if sf not in _gates:
        _gates[sf] = SiteGate(sf)
    return _gates[sf]


def reset_gates() -> None:  # tests
    _gates.clear()


# ----------------------------------------------------------------- alerts ---
async def notify_admin(text: str) -> None:
    """Short alert to the bot owner (falls back to the log channel).  Never raises."""
    targets = [Vars.OWNER] if Vars.OWNER else ([Vars.LOG_CHANNEL] if Vars.LOG_CHANNEL else [])
    for chat in targets:
        try:
            await retry_on_flood(Bot.send_message)(chat, text)
        except Exception as err:
            logger.warning(f"admin alert failed: {err}")


# --------------------------------------------------------------- failures ---
def _fcol():
    return database._db.chapter_failures


def _fid(map_id, key) -> str:
    return f"{map_id}:{key}"


async def failure_attempts(map_id, key) -> int:
    doc = await _fcol().find_one({"_id": _fid(map_id, key)})
    return int(doc.get("attempts", 0)) if doc else 0


async def add_failure(map_id, key, title: str, error: str) -> int:
    doc = await _fcol().find_one_and_update(
        {"_id": _fid(map_id, key)},
        {"$inc": {"attempts": 1},
         "$set": {"map_id": int(map_id), "key": key, "title": title, "error": (error or "")[:300], "at": time.time()}},
        upsert=True, return_document=True,
    )
    return int(doc["attempts"])


async def clear_failure(map_id, key) -> None:
    await _fcol().delete_one({"_id": _fid(map_id, key)})


async def list_failures(map_id=None) -> List[dict]:
    flt = {"map_id": int(map_id)} if map_id is not None else {}
    return [d async for d in _fcol().find(flt).sort("at", 1)]


async def reset_failures(map_id=None) -> int:
    flt = {"map_id": int(map_id)} if map_id is not None else {}
    result = await _fcol().delete_many(flt)
    return result.deleted_count


# ---------------------------------------------------------------- scraping ---
async def scrape_chapters(web, doc: dict) -> List[dict]:
    """Chapter list (newest first, as the site gives it) for one mapping."""
    wdata = {"url": doc["series_url"], "title": doc["title"]}
    if doc.get("poster") and doc.get("description"):      # legacy mappings (no details yet) re-detect the cover
        wdata["poster"] = doc["poster"]
    data = await asyncio.wait_for(web.get_chapters(wdata, page=1), SCRAPE_TIMEOUT)
    return await asyncio.to_thread(lambda: web.iter_chapters(data, page=1)) or []


def _site_of(doc):
    from TG.storage import get_webs
    return get_webs(doc["site"])


# ------------------------------------------------------------- enqueueing ---
def disk_ok() -> bool:
    """False when the disk is nearly full - auto uploads wait instead of failing half-way."""
    if not Vars.MIN_FREE_MB:
        return True
    try:
        return shutil.disk_usage(".").free / (1024 * 1024) >= Vars.MIN_FREE_MB
    except Exception:
        return True


async def auto_upload_enabled(owner_id) -> bool:
    """The owner's `auto upload on|off` setting (default on)."""
    try:
        settings = await database.get_settings(owner_id) or {}
    except Exception:
        return True
    return settings.get("auto_upload", True) is not False


async def _fetch_pictures(web, chapter) -> list:
    return await asyncio.wait_for(web.get_pictures(chapter["url"], chapter), SCRAPE_TIMEOUT) or []


async def enqueue_chapter(doc: dict, chapter: dict, web, *, settle: bool = True, extra=()) -> bool:
    """Fetch the pictures of a chapter (plus `extra` chapters merged into the same file, Settings > Merge
    Size) and put ONE channel task in the queue.

    settle=True (new chapters): the page list is read twice, SETTLE_SECONDS apart; if the count or
    the last image changed, the site is still uploading the chapter - try again on the next poll."""
    chapters = [chapter, *extra]
    key = chapter["_key"]
    if queue.has_map_chapter(doc["_id"], key):
        return False
    if not disk_ok():
        logger.warning(f"disk almost full - chapter {key} of #{doc['_id']} waits")
        return False

    pictures = []
    for ch in chapters:
        got = await _fetch_pictures(web, ch)
        if not got:
            attempts = await add_failure(doc["_id"], key, ch.get("title", key), "no pictures found")
            await _maybe_alert_failed(doc, key, ch.get("title", key), "no pictures found", attempts)
            return False
        pictures.extend(got)

    if settle and Vars.SETTLE_SECONDS and len(chapters) == 1:
        await asyncio.sleep(Vars.SETTLE_SECONDS)
        again = await _fetch_pictures(web, chapter)
        if len(again) != len(pictures) or (again and again[-1] != pictures[-1]):
            logger.info(f"chapter {key} of #{doc['_id']} is still being uploaded by the site - next poll")
            return False
        pictures = again

    settings = await database.get_settings(doc["owner_id"]) or {}
    settings = dict(settings) or {"_auto": True}  # non-empty, so the queue does not load the *channel's* settings

    card = TaskCard(
        data_list=[{**c, "manga_title": c.get("manga_title") or doc["title"]} for c in chapters],
        picturesList=pictures, webs=web, sts=None,
        user_id=int(doc["channel_id"]), chat_id=int(doc["channel_id"]),
        priority=0, update_mode=True, settings=settings, kind="auto",
    )
    card.map_id = doc["_id"]
    card.chapter_key = key
    card.owner_id = int(doc["owner_id"])
    card.target_title = doc.get("channel_title") or str(doc["channel_id"])
    keys = [c["_key"] for c in chapters]
    card.on_success = make_on_success(doc, keys, len(pictures))
    card.on_failure = make_on_failure(doc, chapter)
    await queue.put(card, True)
    return True


# ------------------------------------------------------------------ batch ---
_locks: Dict[int, asyncio.Lock] = {}


def _lock(map_id) -> asyncio.Lock:
    return _locks.setdefault(int(map_id), asyncio.Lock())


async def merge_size(owner_id) -> int:
    """Settings > Merge Size (chapters per file); 1 when unset or invalid."""
    try:
        settings = await database.get_settings(owner_id) or {}
        return max(1, min(int(settings.get("megre") or 1), 50))
    except Exception:
        return 1


def _range_label(items: List[dict]) -> str:
    keys = [i["key"] for i in items]
    if not keys:
        return ""
    return f"{keys[0]}" if len(keys) == 1 else f"{keys[0]}-{keys[-1]}"


async def refill_batch(map_id) -> dict:
    """Keep BATCH_DEPTH chapters of a batch mapping in the queue; finish the batch when nothing is left.

    Safe to call at any time and from several places (per-mapping lock + has_map_chapter guard)."""
    out = {"queued": 0, "finished": False, "blocked": None}
    async with _lock(map_id):
        doc = await chmap.get_map(map_id)
        if not doc or doc.get("state") != chmap.STATE_BATCH or doc.get("status") != chmap.STATUS_ACTIVE:
            return out
        if not await auto_upload_enabled(doc["owner_id"]):
            out["blocked"] = "auto upload is off"
            return out
        web = _site_of(doc)
        if web is None:
            out["blocked"] = f"site '{doc['site']}' is not available"
            return out

        posted = set(doc.get("posted", []))
        todo = [i for i in doc.get("batch_items", []) if i["key"] not in posted]
        if not todo:
            await finish_batch(doc)
            out["finished"] = True
            return out

        in_flight = sum(1 for t in queue.auto_pending() if t.map_id == doc["_id"]) + \
                    sum(1 for t in queue.auto_ongoing() if t.map_id == doc["_id"])
        merge = await merge_size(doc["owner_id"])
        groups = [todo[i:i + merge] for i in range(0, len(todo), merge)]   # Settings > Merge Size
        for group in groups:
            item = group[0]
            if in_flight >= Vars.BATCH_DEPTH:
                break
            if queue.has_map_chapter(doc["_id"], item["key"]):
                continue
            if await failure_attempts(doc["_id"], item["key"]) >= Vars.RETRY_LIMIT:
                out["blocked"] = f"chapter {item['key']} failed - Retry/Skip it in /manage"
                break  # keep the channel in order

            def as_chapter(i):
                return {"title": i.get("title") or f"Chapter {i['key']}", "url": i["url"],
                        "manga_title": doc["title"], "poster": doc.get("poster"), "_key": i["key"]}
            chapter = as_chapter(item)
            try:
                if await enqueue_chapter(doc, chapter, web, settle=False, extra=[as_chapter(i) for i in group[1:]]):
                    out["queued"] += 1
                    in_flight += 1
                else:
                    if not disk_ok():
                        out["blocked"] = "disk almost full"
                    break
            except asyncio.CancelledError:
                raise
            except Exception as err:
                attempts = await add_failure(doc["_id"], item["key"], chapter["title"], str(err))
                await _maybe_alert_failed(doc, item["key"], chapter["title"], str(err), attempts)
                out["blocked"] = f"chapter {item['key']}: {err}"[:200]
                break
    return out


async def ensure_details(doc: dict) -> dict:
    """Make sure cover + description + genres are known (older connections have none): read them from the
    series page once and keep them.  Never raises."""
    if doc.get("poster") and doc.get("description") and doc.get("genres") and doc.get("cover_v") == 2:
        return doc
    if not doc.get("_id") or doc.get("details_tried", 0) >= 3:
        return doc
    try:
        from .details import fetch_details
        found = await fetch_details(doc["series_url"])
        fill = {k: found[k] for k in ("description", "genres") if found.get(k) and not doc.get(k)}
        if found.get("poster"):
            fill["poster"] = found["poster"]          # always take the real cover (older ones may be a page card)
            fill["cover_v"] = 2
        if found.get("status") and not doc.get("series_status"):
            fill["series_status"] = found["status"]
        fill["details_tried"] = int(doc.get("details_tried", 0)) + 1
        await chmap.update_map(doc["_id"], **fill)
        return {**doc, **fill}
    except Exception as err:
        logger.warning(f"series details for #{doc.get('_id')} could not be read: {err}")
        return doc


async def _announce(doc: dict, label: str, pages: int, msg=None, many: bool = False) -> bool:
    """Post to the update channel; when that is impossible tell the owner exactly why (never silent)."""
    doc = await ensure_details(doc)
    ok, reason = await announce_chapter(doc, label, pages, msg, many=many)
    if not ok:
        await notify_admin(f"Update post for <b>{doc['title']}</b> ({'chapters ' if many else 'chapter '}{label}) "
                           f"was NOT sent: {reason}")
    return ok


async def finish_batch(doc: dict) -> None:
    """Backlog done: ONE announcement for the whole batch, then the mapping follows new chapters."""
    items = doc.get("batch_items", [])
    await chmap.update_map(doc["_id"], state=chmap.STATE_LIVE, batch_items=[], batch_done_at=time.time(),
                           next_check=time.time() + Vars.POLL_MINUTES * 60)
    if items:
        fresh = await chmap.get_map(doc["_id"]) or doc
        await _announce(fresh, _range_label(items), len(items), None, many=len(items) > 1)


def make_on_success(doc: dict, keys, pages: int):
    keys = [keys] if isinstance(keys, str) else list(keys)

    async def on_success(card: TaskCard, messages) -> None:
        if await chmap.get_map(doc["_id"]) is None:      # mapping was removed while this chapter uploaded
            return
        for key in keys:
            await chmap.record_posted(doc["_id"], key)
            await clear_failure(doc["_id"], key)
        fresh = await chmap.get_map(doc["_id"]) or doc
        if fresh.get("state") == chmap.STATE_BATCH:
            # no per-chapter post during a batch; queue the next chapter right away
            asyncio.create_task(_safe_refill(doc["_id"]))
            return
        label = keys[0] if len(keys) == 1 else f"{keys[0]}-{keys[-1]}"
        await _announce(fresh, label, pages, messages[-1] if messages else None, many=len(keys) > 1)
    return on_success


async def _safe_refill(map_id) -> None:
    try:
        await refill_batch(map_id)
    except Exception as err:
        logger.warning(f"batch refill #{map_id} failed: {err}")


def make_on_failure(doc: dict, chapter: dict):
    async def on_failure(card: TaskCard, reason: str) -> None:
        attempts = await add_failure(doc["_id"], chapter["_key"], chapter.get("title", ""), reason)
        await _maybe_alert_failed(doc, chapter["_key"], chapter.get("title", ""), reason, attempts)
    return on_failure


async def _maybe_alert_failed(doc, key, title, reason, attempts) -> None:
    if attempts == Vars.RETRY_LIMIT:  # exactly once, when the chapter becomes "failed"
        await notify_admin(
            f"✗ <b>{doc['title']}</b> chapter {key} failed {attempts}x\n"
            f"Channel: {doc.get('channel_title') or doc['channel_id']}\n"
            f"Reason: <code>{(reason or '')[:200]}</code>\n"
            f"Later chapters wait. Use /ch_retry {doc['_id']} or /ch_skip {doc['_id']} {key}"
        )


# ----------------------------------------------------------------- checking ---
async def check_map(doc: dict, *, force: bool = False) -> dict:
    """Check ONE mapping.  Returns {'queued': n, 'error': str|None, 'skipped': str|None}."""
    out = {"queued": 0, "error": None, "skipped": None}
    if doc.get("state") == chmap.STATE_BATCH:
        res = await refill_batch(doc["_id"])
        out["queued"] = res["queued"]
        out["skipped"] = res["blocked"]
        await chmap.update_map(doc["_id"], last_checked=time.time(), next_check=time.time() + 60)
        return out
    if not await auto_upload_enabled(doc["owner_id"]):
        out["skipped"] = "auto upload is off"
        await chmap.mark_checked(doc["_id"], ok=True)
        return out
    web = _site_of(doc)
    if web is None:
        out["error"] = f"site '{doc['site']}' is not available in this bot"
        await chmap.mark_checked(doc["_id"], ok=False, error=out["error"])
        return out

    gate = gate_for(web.sf)
    if gate.is_down and not force:
        out["skipped"] = f"{web.sf} is marked down until {time.strftime('%H:%M', time.localtime(gate.down_until))}"
        return out

    try:
        async with gate.sem:
            chapters = await scrape_chapters(web, doc)
            await asyncio.sleep(Vars.SITE_DELAY)
        if not chapters:
            raise RuntimeError("no chapters found (site blocked, series moved, or layout changed)")
        gate.ok()
    except asyncio.CancelledError:
        raise
    except Exception as err:
        out["error"] = f"{type(err).__name__}: {err}"[:300]
        if gate.fail(out["error"]):
            await notify_admin(f"✕ Site <b>{web.sf}</b> failed {SITE_FAIL_LIMIT}x in a row - pausing it for "
                               f"{SITE_DOWN_SECONDS // 60} min.\nLast error: <code>{gate.last_error}</code>")
        await chmap.mark_checked(doc["_id"], ok=False, error=out["error"])
        return out

    # remember a cover image if the mapping has none yet
    details = chmap.details_from(chapters)       # cover / description / genres for the update poster
    fill = {}
    if details["poster"] and (not doc.get("poster") or not doc.get("description")):
        fill["poster"] = details["poster"]
    if not doc.get("description") and details["description"]:
        fill["description"] = details["description"]
    if not doc.get("genres") and details["genres"]:
        fill["genres"] = details["genres"]
    if not doc.get("series_status") and details["status"]:
        fill["series_status"] = details["status"]
    if fill:
        await chmap.update_map(doc["_id"], **fill)
        doc = {**doc, **fill}

    fresh = await chmap.get_map(doc["_id"]) or doc
    pending = chmap.new_chapters(chapters, fresh.get("posted", []))

    if len(pending) > BURST_LIMIT and not force:
        await chmap.update_map(doc["_id"], status=chmap.STATUS_ERROR,
                               last_error=f"{len(pending)} new chapters at once - paused for safety")
        await notify_admin(
            f"▲ <b>{doc['title']}</b>: {len(pending)} 'new' chapters appeared at once, so I paused it "
            f"(site layout change?).\nCheck with /ch_info {doc['_id']}, then /ch_resume {doc['_id']} "
            f"or post a range with /ch_backfill.")
        out["error"] = "burst limit"
        return out

    for chapter in pending:
        key = chapter["_key"]
        if await failure_attempts(doc["_id"], key) >= Vars.RETRY_LIMIT:
            break  # failed chapter blocks the later ones (channel order); /ch_retry or /ch_skip
        try:
            if await enqueue_chapter(fresh, chapter, web):
                out["queued"] += 1
        except asyncio.CancelledError:
            raise
        except Exception as err:
            out["error"] = f"chapter {key}: {err}"[:300]
            attempts = await add_failure(doc["_id"], key, chapter.get("title", ""), str(err))
            await _maybe_alert_failed(fresh, key, chapter.get("title", ""), str(err), attempts)
            break  # keep order: don't try later chapters before this one works
        await asyncio.sleep(Vars.SITE_DELAY)

    await chmap.mark_checked(
        doc["_id"], ok=out["error"] is None,
        error=out["error"], poll_seconds=int(Vars.POLL_MINUTES * 60 * random.uniform(0.9, 1.1)),
    )
    return out


async def poll_once(only: Optional[List[dict]] = None) -> dict:
    """Check all due mappings (or `only`).  Sites run in parallel, each limited by its SiteGate."""
    maps = only if only is not None else await chmap.due_maps()
    stats = {"checked": 0, "queued": 0, "errors": 0, "skipped": 0}
    if not maps:
        return stats

    by_site: Dict[str, List[dict]] = {}
    for doc in maps:
        by_site.setdefault(doc["site"], []).append(doc)

    async def run_site(docs: List[dict]):
        async def one(doc):
            try:
                res = await asyncio.wait_for(check_map(doc, force=only is not None), SCRAPE_TIMEOUT * 6)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                logger.exception(f"check_map crashed for #{doc['_id']}: {err}")
                await chmap.mark_checked(doc["_id"], ok=False, error=str(err))
                res = {"queued": 0, "error": str(err), "skipped": None}
            stats["checked"] += 1
            stats["queued"] += res["queued"]
            stats["errors"] += 1 if res["error"] else 0
            stats["skipped"] += 1 if res["skipped"] else 0
        await asyncio.gather(*(one(d) for d in docs))

    await asyncio.gather(*(run_site(docs) for docs in by_site.values()))
    return stats


async def poll_loop() -> None:
    """Background job started by main.py."""
    await chmap.ensure_indexes()
    await asyncio.sleep(15)  # let the bot finish starting
    while True:
        try:
            for doc in await chmap.batch_maps():      # resume / keep feeding batches (also after a restart)
                await _safe_refill(doc["_id"])
            stats = await poll_once()
            if stats["checked"]:
                logger.info(f"auto-poll: {stats}")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.exception(f"poll loop error: {err}")
        await asyncio.sleep(60)

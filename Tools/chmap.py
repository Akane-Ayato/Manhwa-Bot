"""Channel mapping: manhwa series  ->  Telegram channel (auto-posted).

Pure logic + MongoDB access, no Telegram handlers (those are in TG/chmap_cmds.py),
so everything here is unit-testable.

Collections (all in the normal bot database):
  channel_maps   one document per (series_url, channel_id)
  counters       sequential short ids  (so you can say `/ch_info 17`)
"""
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

from config import Vars
from .db import database, get_episode_number

STATUS_ACTIVE, STATUS_PAUSED, STATUS_ERROR = "active", "paused", "error"
MODE_LATEST, MODE_BATCH = "latest", "batch"
STATE_LIVE, STATE_BATCH = "live", "batch"      # batch = still working through the initial backlog
MAX_POSTED_KEPT = 5000   # chapter keys remembered per mapping (way above any real series)


# ---------------------------------------------------------------- parsing ---
class MapError(ValueError):
    """User-facing validation problem (message is shown as is)."""


_CHANNEL_RE = re.compile(r"^-100\d{5,}$")


def parse_map_args(text: str) -> Tuple[str, str, int]:
    """`<name...> <url> <channel_id>` -> (name, url, channel_id).

    The LAST token is the channel id, the one before it the URL, everything before is
    the name - so manga names may contain spaces, dashes, quotes, etc.
    """
    tokens = (text or "").split()
    if len(tokens) < 3:
        raise MapError("Need 3 parts: <manga name> <manga url> <channel id>")

    raw_chat, url = tokens[-1], tokens[-2]
    name = " ".join(tokens[:-2]).strip(" -–—\"'")

    if not _CHANNEL_RE.match(raw_chat):
        raise MapError(f"Channel id must look like -1001234567890 (got `{raw_chat}`)")
    if not re.match(r"^https?://", url, re.I):
        raise MapError(f"Second-to-last part must be the manga page URL (got `{url}`)")
    if not name:
        raise MapError("Manga name is missing")
    return name, url, int(raw_chat)


def parse_import_lines(text: str) -> Tuple[List[Tuple[str, str, int]], List[Tuple[int, str, str]]]:
    """Bulk format: one `<name> <url> <channel_id>` per line (blank lines and `#` comments skipped).

    Returns (valid [(name, url, chat)], errors [(line_no, line, reason)])."""
    ok, bad = [], []
    for no, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            ok.append(parse_map_args(line))
        except MapError as err:
            bad.append((no, line[:80], str(err)))
    return ok, bad


# ------------------------------------------------------------------ sites ---
def _host(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def detect_site(url: str, web_data: dict):
    """Return the scraper whose domain matches `url` and which is allowed for mapping, else None."""
    host = _host(url)
    if not host:
        return None
    for web in web_data.values():
        if web.sf not in Vars.MAP_SITES:
            continue
        if _host(web.url) == host:
            return web
    return None


def allowed_site_names(web_data: dict) -> str:
    return ", ".join(w.url.replace("https://", "").replace("http://", "").strip("/")
                     for w in web_data.values() if w.sf in Vars.MAP_SITES)


def chapter_key(title: str) -> Optional[str]:
    """Stable key for a chapter ("Chapter 10.50 - x" -> "10.5").  None when no number is found."""
    num = get_episode_number(title or "")
    if not num:
        return None
    try:
        value = float(num)
    except (TypeError, ValueError):
        return None
    return str(int(value)) if value == int(value) else repr(value)


def details_from(chapters: List[dict]) -> dict:
    """Cover / description / genres / status of the series, taken from the scraped chapter list."""
    out = {"poster": None, "description": "", "genres": [], "status": ""}
    for chapter in chapters:
        for key in out:
            if not out[key] and chapter.get(key):
                out[key] = chapter[key]
    return out


def chapter_value(key) -> float:
    try:
        return float(key)
    except (TypeError, ValueError):
        return -1.0


# --------------------------------------------------------------- database ---
def _col():
    return database._db.channel_maps


def _counters():
    return database._db.counters


async def next_id() -> int:
    doc = await _counters().find_one_and_update(
        {"_id": "channel_maps"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True,
    )
    return int(doc["seq"])


async def ensure_indexes() -> None:
    try:
        await _col().create_index([("series_url", 1), ("channel_id", 1)], unique=True)
        await _col().create_index([("status", 1), ("next_check", 1)])
    except Exception as err:  # index problems must not stop the bot
        logger.warning(f"channel_maps index creation failed: {err}")


async def add_map(*, title: str, site: str, series_url: str, channel_id: int, channel_title: str,
                  owner_id: int, last_chapter: Optional[str], posted: List[str],
                  invite_link: Optional[str] = None, poster: Optional[str] = None,
                  mode: str = MODE_LATEST, batch_items: Optional[List[dict]] = None,
                  description: str = "", genres: Optional[List[str]] = None, status_text: str = "") -> dict:
    series_url = series_url.strip()
    if await _col().find_one({"series_url": series_url, "channel_id": channel_id}):
        raise MapError("This manga URL is already mapped to that channel")
    doc = {
        "_id": await next_id(),
        "title": title, "site": site, "series_url": series_url,
        "channel_id": channel_id, "channel_title": channel_title or "",
        "invite_link": invite_link, "poster": poster,
        "description": description or "", "genres": list(genres or []), "series_status": status_text or "",
        "owner_id": owner_id, "last_chapter": last_chapter, "posted": list(posted)[-MAX_POSTED_KEPT:],
        "status": STATUS_ACTIVE, "fail_count": 0, "last_error": None,
        "last_checked": 0, "next_check": 0, "created_at": time.time(), "posted_count": 0,
        # batch = upload every chapter present now, then follow new ones; latest = only future chapters
        "mode": mode,
        "state": STATE_BATCH if (mode == MODE_BATCH and batch_items) else STATE_LIVE,
        "batch_items": list(batch_items or []), "batch_total": len(batch_items or []),
    }
    await _col().insert_one(doc)
    return doc


async def get_map(map_id) -> Optional[dict]:
    try:
        return await _col().find_one({"_id": int(map_id)})
    except (TypeError, ValueError):
        return None


async def find_maps(query: str) -> List[dict]:
    """`17` -> mapping #17; otherwise case-insensitive name search."""
    query = (query or "").strip()
    if not query:
        return []
    if query.isdigit():
        doc = await get_map(query)
        return [doc] if doc else []
    out = []
    pattern = {"$regex": re.escape(query), "$options": "i"}
    async for doc in _col().find({"title": pattern}).sort("_id", 1):
        out.append(doc)
    return out


async def list_maps(status: Optional[str] = None, channel_id: Optional[int] = None) -> List[dict]:
    flt = {}
    if status:
        flt["status"] = status
    if channel_id is not None:
        flt["channel_id"] = channel_id
    return [d async for d in _col().find(flt).sort("_id", 1)]


async def count_maps() -> dict:
    out = {STATUS_ACTIVE: 0, STATUS_PAUSED: 0, STATUS_ERROR: 0}
    async for doc in _col().find({}, {"status": 1}):
        out[doc.get("status", STATUS_ACTIVE)] = out.get(doc.get("status", STATUS_ACTIVE), 0) + 1
    return out


async def update_map(map_id, **fields) -> bool:
    result = await _col().update_one({"_id": int(map_id)}, {"$set": fields})
    return result.matched_count > 0


async def delete_map(map_id) -> bool:
    result = await _col().delete_one({"_id": int(map_id)})
    return result.deleted_count > 0


async def batch_maps() -> List[dict]:
    """Active mappings that are still uploading their initial backlog."""
    return [d async for d in _col().find({"status": STATUS_ACTIVE, "state": STATE_BATCH}).sort("_id", 1)]


async def due_maps(now: Optional[float] = None) -> List[dict]:
    """Active mappings whose next_check has passed."""
    now = time.time() if now is None else now
    return [d async for d in _col().find(
        {"status": STATUS_ACTIVE, "next_check": {"$lte": now}}).sort("_id", 1)]


async def mark_checked(map_id, *, ok: bool, error: Optional[str] = None, poll_seconds: Optional[int] = None) -> None:
    poll = (poll_seconds if poll_seconds is not None else Vars.POLL_MINUTES * 60)
    now = time.time()
    if ok:
        await update_map(map_id, last_checked=now, next_check=now + poll, fail_count=0, last_error=None)
        return
    doc = await get_map(map_id) or {}
    fails = int(doc.get("fail_count", 0)) + 1
    backoff = min(poll * (2 ** min(fails, 4)), 6 * 3600)  # 2x, 4x ... up to 6h
    await update_map(map_id, last_checked=now, next_check=now + backoff, fail_count=fails,
                     last_error=(error or "")[:300])


async def record_posted(map_id, key: str) -> None:
    """Remember a chapter as posted (only called after the upload succeeded)."""
    doc = await get_map(map_id)
    if not doc:
        return
    posted = list(doc.get("posted", []))
    if key not in posted:
        posted.append(key)
    posted = posted[-MAX_POSTED_KEPT:]
    last = doc.get("last_chapter")
    if last is None or chapter_value(key) > chapter_value(last):
        last = key
    await _col().update_one({"_id": int(map_id)}, {
        "$set": {"posted": posted, "last_chapter": last, "fail_count": 0, "last_error": None},
        "$inc": {"posted_count": 1},
    })


# ------------------------------------------------------------ new chapters ---
def new_chapters(chapters: List[dict], posted: List[str], baseline_missing: bool = False) -> List[dict]:
    """Chapters of the scraped list that were never posted, oldest first, one per chapter number.

    Chapters without a number are skipped (cannot be ordered or de-duplicated safely)."""
    seen = set(posted)
    out, used = [], set()
    for chapter in chapters:
        key = chapter_key(chapter.get("title", ""))
        if key is None or key in seen or key in used:
            continue
        used.add(key)
        out.append({**chapter, "_key": key})
    out.sort(key=lambda c: chapter_value(c["_key"]))
    return out

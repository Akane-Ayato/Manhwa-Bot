"""Operations behind the /ch_* commands (no message formatting, no handlers) - unit-testable."""
import asyncio
from typing import List, Optional, Tuple

from loguru import logger

from bot import Bot
from config import Vars
from . import chmap, chpoller
from .chmap import MapError


# ---------------------------------------------------------- channel checks ---
async def check_channel(channel_id: int, bot=None) -> Tuple[str, bool]:
    """Verify the bot can post in `channel_id`.  Returns (title, can_invite_users).

    Raises MapError with a plain-language reason otherwise."""
    bot = bot or Bot
    try:
        chat = await bot.get_chat(channel_id)
    except Exception as err:
        raise MapError(f"I cannot see that channel ({type(err).__name__}). Add the bot to it as admin first.")

    ctype = str(getattr(getattr(chat, "type", ""), "name", getattr(chat, "type", ""))).upper()
    if ctype not in ("CHANNEL", "SUPERGROUP", "GROUP"):
        raise MapError("That id is not a channel or group")

    try:
        me = await bot.get_chat_member(channel_id, "me")
    except Exception as err:
        raise MapError(f"The bot is not a member of that channel ({type(err).__name__}).")

    status = str(getattr(getattr(me, "status", ""), "name", getattr(me, "status", ""))).upper()
    if status not in ("ADMINISTRATOR", "OWNER"):
        raise MapError("The bot is not an admin there. Promote it (post messages + invite users) and retry.")

    rights = getattr(me, "privileges", None)
    if status == "ADMINISTRATOR" and rights is not None:
        if ctype == "CHANNEL" and not getattr(rights, "can_post_messages", False):
            raise MapError("The bot is admin but lacks the 'Post messages' right in that channel.")
    can_invite = bool(getattr(rights, "can_invite_users", True)) if rights is not None else True
    return (getattr(chat, "title", None) or str(channel_id)), can_invite


async def make_invite_link(channel_id: int, bot=None) -> Optional[str]:
    """Join-REQUEST link (people ask to join, you approve).  None when the bot may not create links."""
    bot = bot or Bot
    try:
        link = await bot.create_chat_invite_link(channel_id, name="Join request", creates_join_request=True)
        return getattr(link, "invite_link", None)
    except Exception as err:
        logger.warning(f"could not create invite link for {channel_id}: {err}")
        return None


# ----------------------------------------------------------------- mapping ---
async def create_mapping(name: str, url: str, channel_id: int, owner_id: int,
                         last_n: int = 0, bot=None, check_site=True, mode: str = chmap.MODE_LATEST) -> dict:
    """Validate + store one mapping.  Returns a result dict for the reply message.

    result = {doc, latest, total_chapters, queued, invite_ok}"""
    from TG.storage import web_data  # late: TG.storage imports a lot

    web = chmap.detect_site(url, web_data)
    if web is None:
        raise MapError("Unsupported site. Supported: " + chmap.allowed_site_names(web_data))

    channel_title, can_invite = await check_channel(channel_id, bot)

    # the series page must really work (title + chapter list)
    probe = {"_id": 0, "series_url": url, "title": name, "poster": None}
    try:
        async with chpoller.gate_for(web.sf).sem:
            chapters = await chpoller.scrape_chapters(web, probe)
    except Exception as err:
        raise MapError(f"Could not read that page ({type(err).__name__}: {str(err)[:120]}). Check the URL.")
    if not chapters:
        raise MapError("The page loaded but no chapters were found - is this the manga detail page URL?")

    numbered = chmap.new_chapters(chapters, [])  # oldest first, de-duplicated
    if not numbered:
        raise MapError("Chapters were found but none has a readable number")
    keys = [c["_key"] for c in numbered]
    last_n = max(0, min(int(last_n or 0), 20))
    batch = mode == chmap.MODE_BATCH
    baseline = [] if batch else (keys[:-last_n] if last_n else keys)   # newest `last_n` count as NEW
    batch_items = [{"key": c["_key"], "url": c["url"], "title": c.get("title", "")} for c in numbered] if batch else []

    details = chmap.details_from(chapters)
    cover = details["poster"]
    invite = await make_invite_link(channel_id, bot) if can_invite else None

    doc = await chmap.add_map(
        title=name, site=web.sf, series_url=url, channel_id=channel_id, channel_title=channel_title,
        owner_id=owner_id, last_chapter=baseline[-1] if baseline else None, posted=baseline,
        invite_link=invite, poster=cover, mode=mode, batch_items=batch_items,
        description=details["description"], genres=details["genres"], status_text=details["status"],
    )

    queued = 0
    if batch:
        queued = (await chpoller.refill_batch(doc["_id"]))["queued"]
    elif last_n:
        res = await chpoller.check_map(doc, force=True)
        queued = res["queued"]
    else:
        await chmap.mark_checked(doc["_id"], ok=True)

    return {"doc": doc, "latest": keys[-1], "total_chapters": len(keys), "queued": queued,
            "invite_ok": bool(invite), "site_name": web.url}


async def backfill(doc: dict, low: float, high: float) -> dict:
    """Queue chapters low..high of a series regardless of what was posted before."""
    from TG.storage import get_webs

    web = get_webs(doc["site"])
    if web is None:
        raise MapError("site not available")
    async with chpoller.gate_for(web.sf).sem:
        chapters = await chpoller.scrape_chapters(web, doc)
    wanted = [c for c in chmap.new_chapters(chapters, []) if low <= chmap.chapter_value(c["_key"]) <= high]
    if not wanted:
        raise MapError("No chapters of that series in this range")
    if len(wanted) > 50:
        raise MapError(f"{len(wanted)} chapters is too many for one backfill (max 50)")

    queued = 0
    for chapter in wanted:
        await chpoller.clear_failure(doc["_id"], chapter["_key"])
        try:
            if await chpoller.enqueue_chapter(doc, chapter, web):
                queued += 1
        except Exception as err:
            logger.warning(f"backfill chapter {chapter['_key']} failed: {err}")
    return {"found": len(wanted), "queued": queued}


async def remove_mapping(map_id: int) -> bool:
    """Delete the mapping AND everything tied to it (queued tasks, failure records, locks)."""
    await queue_drop(map_id)
    await chpoller.reset_failures(map_id)
    chpoller._locks.pop(int(map_id), None)
    return await chmap.delete_map(map_id)


async def queue_drop(map_id: int) -> int:
    return await chpoller.queue.delete_map_tasks(map_id)


async def set_status(map_id: int, status: str) -> bool:
    if status == chmap.STATUS_PAUSED:
        await queue_drop(map_id)
    fields = {"status": status}
    if status == chmap.STATUS_ACTIVE:
        fields.update(next_check=0, last_error=None, fail_count=0)
    return await chmap.update_map(map_id, **fields)


async def resolve(query: str) -> Tuple[Optional[dict], List[dict]]:
    """`17` / name -> (exact mapping or None, all matches)."""
    matches = await chmap.find_maps(query)
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def export_lines(docs: List[dict]) -> str:
    """The same format /ch_import reads."""
    return "\n".join(f"{d['title']} {d['series_url']} {d['channel_id']}" for d in docs) + "\n"


async def import_many(entries: List[Tuple[str, str, int]], owner_id: int, bot=None,
                      on_progress=None, parallel: int = 3) -> dict:
    """Create many mappings; keeps going on errors.  Returns {ok: [...], failed: [(line, reason)]}"""
    ok, failed = [], []
    sem = asyncio.Semaphore(parallel)
    done = 0

    async def one(name, url, chat):
        nonlocal done
        async with sem:
            try:
                res = await create_mapping(name, url, chat, owner_id, bot=bot)
                ok.append(res["doc"])
            except MapError as err:
                failed.append((f"{name} {chat}", str(err)))
            except Exception as err:
                failed.append((f"{name} {chat}", f"{type(err).__name__}: {err}"[:120]))
            done += 1
            if on_progress:
                try:
                    await on_progress(done, len(entries))
                except Exception:
                    pass

    await asyncio.gather(*(one(*e) for e in entries))
    return {"ok": ok, "failed": failed}


async def start_batch(map_id: int) -> dict:
    """Upload every chapter of the series that was not posted yet (oldest first), then follow new ones."""
    doc = await chmap.get_map(map_id)
    if not doc:
        raise MapError("mapping not found")
    web = _web_of(doc)
    async with chpoller.gate_for(web.sf).sem:
        chapters = await chpoller.scrape_chapters(web, doc)
    posted = set(doc.get("posted", []))
    items = [{"key": c["_key"], "url": c["url"], "title": c.get("title", "")}
             for c in chmap.new_chapters(chapters, []) if c["_key"] not in posted]
    if not items:
        raise MapError("Nothing is missing - every chapter on the site was already posted")
    await chmap.update_map(map_id, mode=chmap.MODE_BATCH, state=chmap.STATE_BATCH, batch_items=items,
                           batch_total=len(items), status=chmap.STATUS_ACTIVE, last_error=None)
    await chpoller.reset_failures(map_id)
    res = await chpoller.refill_batch(map_id)
    return {"total": len(items), "queued": res["queued"]}


async def stop_batch(map_id: int) -> bool:
    """Leave batch mode: drop waiting batch chapters, only NEW chapters are posted from now on."""
    await queue_drop(map_id)
    return await chmap.update_map(map_id, mode=chmap.MODE_LATEST, state=chmap.STATE_LIVE, batch_items=[],
                                  next_check=0)


async def change_channel(map_id: int, channel_id: int, bot=None) -> str:
    """Move a series to another channel (rights are checked first, a new join-request link is made)."""
    title, can_invite = await check_channel(channel_id, bot)
    link = await make_invite_link(channel_id, bot) if can_invite else None
    await queue_drop(map_id)
    await chmap.update_map(map_id, channel_id=int(channel_id), channel_title=title, invite_link=link)
    return title


def _web_of(doc):
    from TG.storage import get_webs
    web = get_webs(doc["site"])
    if web is None:
        raise MapError("site not available")
    return web

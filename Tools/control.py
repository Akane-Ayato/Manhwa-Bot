"""Owner/admin control state: persisted admins, bans, maintenance mode, and the /stats numbers.

Collections: bot_admins, bot_banned, bot_state.  Everything is cached in memory (the gate runs on
every message) and written through to MongoDB so it survives restarts.
"""
import time
from typing import List, Optional

from loguru import logger

from config import Vars
from .db import database

BANNED: set = set()
STATE = {"maintenance": False}


def _admins():
    return database._db.bot_admins


def _banned():
    return database._db.bot_banned


def _state():
    return database._db.bot_state


async def load() -> None:
    """Called once at start-up."""
    try:
        async for doc in _admins().find({}):
            if int(doc["_id"]) not in Vars.ADMINS:
                Vars.ADMINS.append(int(doc["_id"]))
        BANNED.clear()
        async for doc in _banned().find({}):
            BANNED.add(int(doc["_id"]))
        st = await _state().find_one({"_id": "state"}) or {}
        STATE["maintenance"] = bool(st.get("maintenance"))
    except Exception as err:  # the bot must still start without these
        logger.warning(f"control state could not be loaded: {err}")


def is_owner(uid) -> bool:
    return bool(uid) and int(uid) == int(Vars.OWNER or 0)


def is_banned(uid) -> bool:
    return int(uid) in BANNED


def maintenance() -> bool:
    return STATE["maintenance"]


async def set_maintenance(on: bool) -> None:
    STATE["maintenance"] = bool(on)
    await _state().update_one({"_id": "state"}, {"$set": {"maintenance": bool(on), "at": time.time()}}, upsert=True)


async def add_admin(uid: int) -> str:
    uid = int(uid)
    if uid in Vars.ADMINS:
        return "already an admin"
    Vars.ADMINS.append(uid)
    await _admins().update_one({"_id": uid}, {"$set": {"at": time.time()}}, upsert=True)
    return "added"


async def remove_admin(uid: int) -> str:
    uid = int(uid)
    if is_owner(uid):
        return "the owner cannot be removed"
    stored = await _admins().find_one({"_id": uid})
    if uid not in Vars.ADMINS:
        return "not an admin"
    if not stored:
        return "this admin comes from the ADMINS env variable - remove it there"
    Vars.ADMINS.remove(uid)
    await _admins().delete_one({"_id": uid})
    return "removed"


async def ban(uid: int, reason: str = "") -> str:
    uid = int(uid)
    if is_owner(uid) or uid in Vars.ADMINS:
        return "admins and the owner cannot be banned"
    BANNED.add(uid)
    await _banned().update_one({"_id": uid}, {"$set": {"reason": reason[:200], "at": time.time()}}, upsert=True)
    return "banned"


async def unban(uid: int) -> str:
    uid = int(uid)
    BANNED.discard(uid)
    res = await _banned().delete_one({"_id": uid})
    return "unbanned" if res.deleted_count else "was not banned"


async def list_banned() -> List[dict]:
    return [d async for d in _banned().find({}).sort("at", 1)]


# ------------------------------------------------------------------ stats ---
async def bot_stats() -> dict:
    from . import chmap, chpoller
    from .base import queue

    t0 = time.perf_counter()
    try:
        await database._db.command("ping") if hasattr(database._db, "command") else None
        db_ms = int((time.perf_counter() - t0) * 1000)
    except Exception:
        db_ms = -1
    users = await database.users.count_documents({})
    premium = await database.acollection.count_documents({})
    maps = await chmap.list_maps()
    by_state = {"active": 0, "paused": 0, "error": 0, "batch": 0}
    for d in maps:
        by_state[d.get("status", "active")] = by_state.get(d.get("status", "active"), 0) + 1
        if d.get("state") == chmap.STATE_BATCH:
            by_state["batch"] += 1
    channels = len({d["channel_id"] for d in maps})
    failures = len(await chpoller.list_failures())
    user_wait = sum(1 for t, _ in queue.storage_data.values() if getattr(t, "kind", "user") == "user")
    user_run = sum(1 for t in queue.ongoing_tasks.values() if getattr(t, "kind", "user") == "user")
    sites = {sf: ("DOWN" if g.is_down else "ok") for sf, g in chpoller._gates.items()}
    return {
        "db_ms": db_ms, "users": users, "premium": premium, "banned": len(BANNED), "admins": len(Vars.ADMINS),
        "maps": len(maps), "channels": channels, "by_state": by_state, "failures": failures,
        "user_wait": user_wait, "user_run": user_run,
        "auto_wait": len(queue.auto_pending()), "auto_run": queue.auto_running(),
        "posted_total": sum(int(d.get("posted_count", 0)) for d in maps),
        "sites": sites, "maintenance": maintenance(),
    }


def stats_text(s: dict) -> str:
    st = s["by_state"]
    sites = ", ".join(f"{k}: {v}" for k, v in s["sites"].items()) or "no checks yet"
    return (
        "\n♚ <b>Bot</b>\n"
        f"├ Mode: {'✦ maintenance' if s['maintenance'] else '● normal'}\n"
        f"├ DB ping: {s['db_ms']} ms\n"
        f"├ Users: {s['users']} · Premium: {s['premium']} · Banned: {s['banned']} · Admins: {s['admins']}\n"
        f"├ Series: {s['maps']} on {s['channels']} channel(s) - ● {st['active']} ‖ {st['paused']} ◉ {st['error']} "
        f"· ❖ batch running {st['batch']}\n"
        f"├ Chapters auto-posted: {s['posted_total']} · failed waiting: {s['failures']}\n"
        f"├ User queue: {s['user_run']} running, {s['user_wait']} waiting\n"
        f"├ Channel queue: {s['auto_run']} running, {s['auto_wait']} waiting\n"
        f"└ Sites: {sites}\n"
    )

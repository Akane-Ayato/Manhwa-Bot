"""Settings > Test Settings: run the REAL upload pipeline on 4 generated pages with the user's own
settings, send the result to the user's DM and report what was applied - so nothing has to be taken on faith.
"""
import os
import shutil
from typing import List, Tuple

from loguru import logger
from PIL import Image, ImageDraw
from types import SimpleNamespace

from bot import Bot
from config import Vars
from . import chmap, chservice
from .base import TaskCard
from .db import database

OK, BAD, INFO = "✓", "✗", "–"


def make_sample_pages(folder: str, count: int = 4) -> List[str]:
    os.makedirs(folder, exist_ok=True)
    urls = []
    for n in range(1, count + 1):
        img = Image.new("RGB", (800, 1100 + n * 60), (30 * n, 60, 200 - 30 * n))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 780, 120], fill=(255, 255, 255))
        draw.text((40, 60), f"TEST PAGE {n} OF {count}", fill=(0, 0, 0))
        path = os.path.abspath(os.path.join(folder, f"sample_{n}.jpg"))
        img.save(path, "JPEG", quality=85)
        urls.append("file://" + path)
    return urls


async def _channel_line(label: str, chat) -> Tuple[str, str, str]:
    if not chat:
        return INFO, label, "not set"
    try:
        title, can_invite = await chservice.check_channel(int(chat))
        return OK, label, f"{title} - bot can post" + ("" if can_invite else " (no invite right)")
    except Exception as err:
        return BAD, label, str(err)[:110]


async def run(user_id: int, chat_id: int) -> List[Tuple[str, str, str]]:
    """Returns report rows (mark, name, detail).  Sends the sample chapter + update-post preview to chat_id."""
    from .cworker import send_manga_chapter
    from . import announce

    settings = await database.get_settings(user_id) or {}
    work = f"Process/stest_{user_id}"
    shutil.rmtree(work, ignore_errors=True)
    pages = make_sample_pages(f"{work}_src")
    rows: List[Tuple[str, str, str]] = []

    card = TaskCard(
        data_list=[{"title": "Chapter 1", "manga_title": "Settings Test", "url": "test://sample", "poster": ""}],
        picturesList=pages, webs=SimpleNamespace(sf="test", url="https://test.local/", cs=False),
        sts=None, user_id=user_id, chat_id=chat_id, priority=0, update_mode=True,
        settings=dict(settings) or {"_t": True}, kind="test", tasks_id=f"stest_{user_id}",
    )
    card.owner_id = user_id
    try:
        await send_manga_chapter(card)
    finally:
        shutil.rmtree(f"{work}_src", ignore_errors=True)

    rep = card.report or {}
    if card.progress.stage != "Posted":
        rows.append((BAD, "Upload", card.fail_reason or "the sample chapter could not be built"))
        return rows

    rows.append((OK, "Upload", f"sample chapter sent to you: {', '.join(rep.get('files', []))}"))
    if settings.get("file_name"):
        rows.append((OK, "File Name", rep["files"][0]))
    if settings.get("caption"):
        rows.append((OK, "Caption", "applied to the file (see the message above)"))
    rows.append((OK, "File Type", " + ".join(rep.get("types", []))))
    if "PDF" in rep.get("types", []):
        rows.append((OK if rep.get("compress") else INFO, "Compress", f"quality {rep.get('compress')}"))
        if settings.get("password"):
            rows.append((OK if rep.get("password") else BAD, "Password", "PDF is locked" if rep.get("password") else "not applied"))
        if settings.get("hyper"):
            rows.append((OK, "Hyper Link", f"banner pages link to {settings['hyper']}"))
    for key, label in (("banner1", "Banner 1"), ("banner2", "Banner 2"), ("thumb", "Thumbnail")):
        if settings.get(key):
            applied = rep.get(key)
            rows.append((OK if applied else BAD, label, "applied" if applied else "set, but the image could not be loaded"))
    if settings.get("megre"):
        rows.append((INFO, "Merge Size", f"{settings['megre']} chapters per file (used by batch and by chapter lists)"))
    for key, label in (("before_post", "Before Post"), ("after_post", "After Post"), ("target_s", "Channel Sticker")):
        if settings.get(key):
            rows.append((OK, label, "sent around the sample file in this chat"))
    rows.append(await _channel_line("Dump Channel", settings.get("dump")))

    # update-channel post: the real renderer, previewed here (not posted to the channel)
    sample = {"_id": None, "title": "Settings Test", "channel_title": "Your Channel", "channel_id": chat_id,
              "owner_id": user_id, "invite_link": "https://t.me/+preview", "poster": None, "site": "test"}
    ok, why = await announce.announce_chapter(sample, "1", len(pages), None, target=chat_id)
    rows.append((OK if ok else BAD, "Update Post", "preview sent to you (text, buttons, sticker as the channel gets them)" if ok else why))
    rows.append(await _channel_line("Update Channel", await announce.update_channel_for(user_id)))

    auto = settings.get("auto_upload", True) is not False
    rows.append((OK if auto else INFO, "Auto Post", "ON - mapped series post by themselves" if auto else "OFF - mapped series are paused"))
    maps = await chmap.list_maps()
    mine = [m for m in maps if m.get("owner_id") == user_id] if user_id not in Vars.ADMINS else maps
    for m in mine[:12]:
        rows.append(await _channel_line(f"Series '{m['title'][:22]}'", m["channel_id"]))
    return rows


def format_report(rows) -> str:
    lines = ["<b>Settings test report</b>", ""]
    for mark, name, detail in rows:
        lines.append(f"{mark} <b>{name}</b>: {detail}")
    bad = sum(1 for r in rows if r[0] == BAD)
    lines += ["", ("All checked settings work." if not bad else f"{bad} problem(s) above - fix them, then run the test again.")]
    return "\n".join(lines)

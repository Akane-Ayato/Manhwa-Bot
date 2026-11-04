"""PROOF that every Settings-panel value reaches a channel (auto) upload and the update-channel post."""
import base64
import io
import os
from types import SimpleNamespace as NS

import PyPDF2
import pytest
from PIL import Image

import Tools.announce as announce
import Tools.cworker as cw
from Tools import chmap, chpoller
from Tools.base import AQueue, TaskCard
from Tools.db import database
from config import Vars
from tests.test_chmap import CH, FakeWeb, add_doc, clean_state, use_web  # noqa: F401
from tests.test_pipeline import Handler, server, fast_retries  # noqa: F401

OWNER = 222
UPD = -100777


def data_uri(color, size=(300, 120)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class Rec:
    """Records everything the bot sends, in order."""
    def __init__(self):
        self.events, self.copies = [], []

    async def send_document(self, chat, path, caption=None, thumb=None, progress=None):
        with open(path, "rb") as f:
            data = f.read()
        self.events.append(("doc", chat, os.path.basename(path), str(caption), thumb and os.path.exists(thumb), data))
        return NS(chat=NS(id=chat), id=len(self.events), document=NS(file_name=os.path.basename(path)),
                  link=f"https://t.me/c/1/{len(self.events)}")

    async def send_media_group(self, chat, media):
        out = []
        for m in media:
            out.append(await self.send_document(chat, m.media, m.caption, getattr(m, "thumb", None)))
        return out

    async def send_message(self, chat, text, reply_markup=None, **k):
        self.events.append(("msg", chat, str(text), reply_markup))
        return NS(id=len(self.events))

    async def send_photo(self, chat, photo, caption=None, reply_markup=None, **k):
        self.events.append(("photo", chat, str(caption), reply_markup))

    async def send_sticker(self, chat, sticker, **k):
        self.events.append(("sticker", chat, sticker))

    async def copy_media_group(self, to, frm, mid, captions=None):
        self.copies.append(to); return []

    async def get_users(self, uid): return NS(mention=lambda: "owner")
    async def get_chat(self, c): return NS(id=c, title="x", type=NS(name="CHANNEL"))
    async def download_media(self, *a, **k): return None
    async def create_chat_invite_link(self, *a, **k): return NS(invite_link="https://t.me/+JOIN")


@pytest.fixture
def env(monkeypatch, tmp_path, server, clean_state):
    monkeypatch.chdir(tmp_path)
    bot = Rec()
    for mod in (cw, announce):
        monkeypatch.setattr(mod, "Bot", bot)
    monkeypatch.setattr(cw.Vars, "CONSTANT_DUMP_CHANNEL", None)
    monkeypatch.setattr(cw.Vars, "LOG_CHANNEL", None)
    monkeypatch.setattr(Vars, "UPDATE_CHANNEL", None)
    monkeypatch.setattr(announce.Vars, "UPDATE_CHANNEL", None)
    monkeypatch.setattr(announce, "make_poster", lambda info: _none())
    return bot, server, clean_state


async def _none():
    return None


async def set_owner(**values):
    await database.ensure_user(OWNER)
    for k, v in values.items():
        await database.set_value(OWNER, k, v)


async def auto_card(server, key="4"):
    settings = await database.get_settings(OWNER)
    card = TaskCard(
        data_list=[{"title": f"Chapter {key}", "manga_title": "Solo Leveling", "url": "u", "poster": ""}],
        picturesList=[f"{server}/ok/{i}" for i in range(1, 4)], webs=NS(sf="xx", url="http://localhost", cs=False),
        sts=None, user_id=CH, chat_id=CH, priority=0, update_mode=True, settings=settings, kind="auto",
        tasks_id="t1")
    card.owner_id = OWNER
    return card


async def test_every_upload_setting_reaches_the_channel_post(env):
    bot, server, _ = env
    await set_owner(
        file_name="Ep {chapter_num} - {manga_title}", caption="<b>{file_name}</b> / {manga_title} / {chapter_num}",
        type=["PDF"], compress="40", password="s3cret", hyper="https://example.com/x",
        banner1=data_uri((250, 0, 0)), banner2=data_uri((0, 0, 250)), thumb=data_uri((0, 250, 0), (90, 90)),
        before_post="BEFORE {manga_title} {chapter_num}", after_post="sticker:AFTERSTK",
        target_s="CHANNELSTK", dump=-100999,
    )
    card = await auto_card(server)
    await cw.send_manga_chapter(card)

    kinds = [e[0] for e in bot.events]
    assert kinds == ["msg", "doc", "sticker", "sticker"], kinds     # before, file, after-sticker, channel sticker
    before, doc, after, chan = bot.events
    assert before[1] == CH and before[2] == "BEFORE Solo Leveling 4"                      # Before Post (with params)
    _, chat, fname, caption, had_thumb, pdf = doc
    assert chat == CH                                                                     # posted to the MAPPED channel
    assert fname == "Ep 4 - Solo Leveling.pdf"                                            # File Name
    assert caption == "<b>Ep 4 - Solo Leveling</b> / Solo Leveling / 4"                   # Caption
    assert had_thumb is True                                                              # Thumbnail (owner's, not the channel's)
    reader = PyPDF2.PdfReader(io.BytesIO(pdf))
    assert reader.is_encrypted and reader.decrypt("s3cret") != 0                          # Password
    assert len(reader.pages) == 5                                                         # banner1 + 3 pages + banner2
    assert after[2] == "AFTERSTK" and chan[2] == "CHANNELSTK"                             # After Post / Channel Sticker
    assert bot.copies == [-100999]                                                        # Dump Channel
    assert not os.path.exists("Process/t1")                                               # disk clean


async def test_file_type_cbz_and_pdf_both_posted(env):
    bot, server, _ = env
    await set_owner(type=["PDF", "CBZ"])
    await cw.send_manga_chapter(await auto_card(server))
    names = [e[2] for e in bot.events if e[0] == "doc"]
    assert len(names) == 2 and names[0].endswith(".pdf") and names[1].endswith(".cbz")


async def test_defaults_when_owner_set_nothing(env):
    bot, server, _ = env
    await database.ensure_user(OWNER)
    await cw.send_manga_chapter(await auto_card(server))
    docs = [e for e in bot.events if e[0] == "doc"]
    assert len(docs) == 1 and docs[0][2].startswith("Chapter 4 Solo") and len(bot.events) == 1


async def test_merge_size_groups_batch_chapters_into_one_file(env, monkeypatch):
    bot, server, cs = env
    use_web(monkeypatch, FakeWeb(titles=("Chapter 4", "Chapter 3", "Chapter 2", "Chapter 1"), server_url=server))
    await set_owner(megre="2")
    doc = await add_doc(posted=(), mode="batch", owner_id=OWNER, batch_items=[
        {"key": str(i), "url": f"https://www.mgeko.cc/c/{i}", "title": f"Chapter {i}"} for i in (1, 2, 3, 4)])
    out = await chpoller.refill_batch(doc["_id"])
    assert out["queued"] == 2
    card, _ = await cs.queue.get(1)
    assert card.chapter_key == "1" and len(card.picturesList) == 6        # chapters 1+2 = ONE file (3 pages each)
    assert "1" in str(card.episode_number) and "2" in str(card.episode_number)


# ---------------------------------------------------------------- update post ---
async def test_update_post_uses_owner_update_channel_text_buttons_sticker(env):
    bot, server, _ = env
    await set_owner(
        update_c=UPD, update_t="NEW: {manga_title} ch {chapter_num} in {channel_title}\n< Read now >{read_link}",
        update_b="Join {channel_title} - {channel_link} | Site - https://example.com", update_s="UPDSTK")
    doc = await add_doc(owner_id=OWNER, invite_link="https://t.me/+JOIN")
    ok, why = await announce.announce_chapter(doc, "4", 3, NS(link="https://t.me/c/1/55"))
    assert ok and why == ""
    msg, stk = bot.events
    assert msg[0] == "msg" and msg[1] == UPD                                              # Update Channel (the owner's, not env)
    assert msg[2].startswith("NEW: Solo Leveling ch 4 in My Channel")                      # Update Text + params
    assert "<a href='https://t.me/c/1/55'>Read now</a>" in msg[2]                          # "< label >link" syntax
    urls = [b.url for row in msg[3].inline_keyboard for b in row]
    assert urls[0] == "https://t.me/+JOIN"                                                 # red join-request button first
    assert "https://example.com" in urls                                                   # Update Button
    assert stk == ("sticker", UPD, "UPDSTK")                                               # Update Sticker


async def test_update_post_default_text_and_no_channel_reason(env):
    bot, server, _ = env
    await set_owner()
    doc = await add_doc(owner_id=OWNER)
    ok, why = await announce.announce_chapter(doc, "4", 3)
    assert not ok and "Update Channel" in why and not bot.events                           # clear reason, not silence
    await set_owner(update_c=UPD)
    ok, _ = await announce.announce_chapter(doc, "1-5", 5, many=True)
    assert ok and bot.events[0][2] == "<b>Solo Leveling</b> chapters <b>1-5</b> added, read now"


async def test_batch_finish_posts_one_update_using_owner_update_channel(env, monkeypatch):
    bot, server, cs = env
    use_web(monkeypatch, FakeWeb(titles=("Chapter 2", "Chapter 1"), server_url=server))
    await set_owner(update_c=UPD)
    items = [{"key": str(i), "url": f"https://www.mgeko.cc/c/{i}", "title": f"Chapter {i}"} for i in (1, 2)]
    doc = await add_doc(posted=(), owner_id=OWNER, mode="batch", batch_items=items)
    await chpoller.refill_batch(doc["_id"])
    for _ in range(2):
        card, _f = await cs.queue.get(1)
        await card.on_success(card, [NS(link="x")])
        await cs.queue.task_done(card)
        import asyncio; await asyncio.sleep(0); await asyncio.sleep(0)
    posts = [e for e in bot.events if e[0] in ("msg", "photo") and e[1] == UPD]
    assert len(posts) == 1 and "chapters <b>1-2</b>" in posts[0][2]                       # ONE post, after everything
    assert (await chmap.get_map(doc["_id"]))["state"] == "live"


async def test_failed_update_post_is_reported_to_owner_not_silent(env, monkeypatch):
    bot, server, cs = env
    await set_owner()                                                                      # no update channel anywhere
    doc = await add_doc(owner_id=OWNER)
    await chpoller._announce(doc, "9", 3)
    assert any("was NOT sent" in a and "Update Channel" in a for a in cs.alerts)

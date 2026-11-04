import time
from types import SimpleNamespace as NS

import pytest

import Tools.uploaders as up
from Tools.auto import _should_send_chapter
from Tools.db import database
from tests.conftest import FakeChannel, FakeMsg


# ---------- fake Telegram bot bound to in-memory channels ----------
class FakeBot:
    def __init__(self, *channels):
        self.channels = {c.id: c for c in channels}
        self.sent = []

    async def get_chat(self, cid):
        c = self.channels[cid]
        return up.Chat(id=c.id, type=up.Chat.__init__.__defaults__ and None) if False else _chat(c)

    async def send_message(self, cid, text, **kw):
        m = self.channels[cid].post(text=text)
        self.sent.append(("msg", cid, text))
        return m

    async def get_messages(self, chat_id, message_ids=None, **kw):
        ch = self.channels[chat_id]
        return [ch.messages.get(i) or FakeMsg(i, empty=True) for i in message_ids]

    async def send_photo(self, cid, photo, caption=None, **kw):
        self.sent.append(("photo", cid, caption)); return self.channels[cid].post(caption=caption)

    async def send_sticker(self, cid, s):
        self.sent.append(("sticker", cid))

    async def copy_media_group(self, to, frm, mid):
        raise ValueError("not a group")

    async def copy_message(self, to, frm, mid, **kw):
        m = self.channels[to].post(document=self.channels[frm].messages[mid].document)
        self.sent.append(("copy", to, mid)); return m


def _chat(c):
    ch = up.Chat.__new__(up.Chat)
    ch.id, ch.title, ch.invite_link, ch.pinned_message = c.id, c.title, c.invite_link, c.pinned_message
    return ch


@pytest.fixture
def world(monkeypatch):
    src = FakeChannel(-1, "source")
    one = FakeChannel(-1001, "Solo Leveling | Manhwa")
    other = FakeChannel(-1002, "Another Series")
    upd = FakeChannel(-1003, "Updates")
    bot = FakeBot(src, one, other, upd)
    monkeypatch.setattr(up, "Bot", bot)
    up.channel_info_cache.clear(); up.channel_msg_cache.clear(); up.channel_photo_cache.clear()
    return bot, src, one, other, upd


async def test_recent_messages_returns_real_messages_and_probe_is_cleaned(world):
    bot, src, one, *_ = world
    one.post(document=NS(file_name="Chapter 1.pdf")); one.post(document=NS(file_name="Chapter 2.pdf"))
    info = await up.get_channel_info(-1001)
    msgs = await info._get_recent_messages(10)
    assert [m.document.file_name for m in msgs if m.document] == ["Chapter 1.pdf", "Chapter 2.pdf"]
    # second call reuses cached id and sees a message posted since
    one.post(document=NS(file_name="Chapter 3.pdf"))
    msgs = await info._get_recent_messages(10)
    assert "Chapter 3.pdf" in [m.document.file_name for m in msgs if m.document]


async def test_upload_goes_to_matching_channel_only_once(world):
    bot, src, one, other, upd = world
    await database.ensure_user(1)
    for ch in (-1001, -1002):
        await database.add_channel(1, "target_channels", ch)
    doc = src.post(document=NS(file_name="Chapter 5 Solo Leveling.pdf"))
    doc.document.file_name
    msg = NS(chat=NS(id=-1), id=doc.id, document=doc.document)
    await up.Uploader().upload_to_targets_channels(msg, "5", "Solo Leveling", "1")
    assert [m.document.file_name for m in one.messages.values() if m.document] == ["Chapter 5 Solo Leveling.pdf"]
    assert not other.messages
    # same chapter again -> duplicate, nothing new
    await up.Uploader().upload_to_targets_channels(msg, "5", "Solo Leveling", "1")
    assert len([m for m in one.messages.values() if m.document]) == 1


async def test_chapter_1_is_not_blocked_by_chapter_10(world):
    bot, src, one, *_ = world
    await database.ensure_user(1); await database.add_channel(1, "target_channels", -1001)
    one.post(document=NS(file_name="Chapter 10 Solo Leveling.pdf"))
    doc = src.post(document=NS(file_name="Chapter 1 Solo Leveling.pdf"))
    msg = NS(chat=NS(id=-1), id=doc.id, document=doc.document)
    await up.Uploader().upload_to_targets_channels(msg, "1", "Solo Leveling", "1")
    assert len([m for m in one.messages.values() if m.document]) == 2     # substring test used to skip it


async def test_title_with_regex_chars_does_not_crash(world):
    bot, src, one, *_ = world
    await database.ensure_user(1); await database.add_channel(1, "target_channels", -1001)
    doc = src.post(document=NS(file_name="x.pdf"))
    msg = NS(chat=NS(id=-1), id=doc.id, document=doc.document)
    for title in ("Who Am I?", "Re:Zero (S2", "a*b[c", "C++ \\ manga"):
        await up.Uploader().upload_to_targets_channels(msg, "1", title, "1")   # re.error used to escape


async def test_empty_title_matches_nothing(world):
    bot, src, one, *_ = world
    await database.ensure_user(1); await database.add_channel(1, "target_channels", -1001)
    doc = src.post(document=NS(file_name="x.pdf"))
    msg = NS(chat=NS(id=-1), id=doc.id, document=doc.document)
    await up.Uploader().upload_to_targets_channels(msg, "1", "Chapter", "1")  # cleans to ""
    assert not [m for m in one.messages.values() if m.document]


async def test_update_notify_posts_once_and_handles_missing_invite_link(world):
    bot, src, one, other, upd = world
    one.invite_link = None                                   # used to crash str.replace
    await database.ensure_user(1)
    await database.set_value(1, "update_c", -1003)
    await database.set_value(1, "update_t", "<b>{manga_title}</b> Ch {chapter_num} {channel_link}")
    info = await up.get_channel_info(-1001)
    post = one.post(document=NS(file_name="c.pdf"))
    await up.update_notify(post, 1, "Solo", 7, info)
    await up.update_notify(post, 1, "Solo", 7, info)         # duplicate announcement -> skipped
    texts = [t for kind, cid, t in bot.sent if cid == -1003 and kind in ("msg",)]
    assert len([m for m in upd.messages.values() if "Solo" in (m.text or m.caption or "")]) == 1


async def test_channel_id_always_numeric(world):
    bot, *_ = world
    info = await up.get_channel_info(-1001)
    assert isinstance(info.id, int)


# ---------- update detection ----------
async def _collect(chapters, last):
    return [c["title"] async for c in _should_send_chapter(chapters, last)]


CH = lambda *n: [{"title": f"Chapter {i}"} for i in n]          # newest first, like the sites


async def test_new_chapters_detected_oldest_first():
    assert await _collect(CH(12, 11, 10, 9), "Chapter 10") == ["Chapter 11", "Chapter 12"]


async def test_no_new_chapter():
    assert await _collect(CH(10, 9), "Chapter 10") == []


async def test_first_run_sends_latest_only():
    assert await _collect(CH(10, 9, 8), None) == ["Chapter 10"]
    assert await _collect([], "Chapter 1") == []


async def test_decimal_chapters():
    assert await _collect(CH(11, 10.5, 10), "Chapter 10") == ["Chapter 10.5", "Chapter 11"]


# ---------- shortener token gate ----------
@pytest.fixture
def tok(monkeypatch):
    import Tools.my_token as t
    monkeypatch.setattr(t.Vars, "SHORTENER", True)
    monkeypatch.setattr(t.Vars, "SHORTENER_API", "https://s.example/api?url={}")
    monkeypatch.setattr(t, "Bot", NS(username="mybot", delete_messages=lambda *a: _noop()))
    async def short(url): return "https://short/" + url[-8:]
    monkeypatch.setattr(t, "get_short", short)
    return t


async def _noop(): return None


class Msg:
    def __init__(self, uid=50):
        self.from_user = NS(id=uid); self.id = 1; self.chat = NS(id=uid); self.out = []
    async def reply(self, text, **kw):
        self.out.append(text); return self
    async def edit(self, text, **kw): self.out.append(text); return self
    edit_text = edit


async def test_gate_full_flow(tok):
    called = []
    @tok.check_token_
    async def handler(c, m): called.append(1)

    m = Msg()
    await handler(None, m)                       # no token -> gets a link, handler not run
    assert not called
    data = await database.get_token_data(50)
    assert data and data["verify"] is None

    await handler(None, Msg())                   # still unverified
    assert not called

    bot_msg = Msg()
    await tok.verify_token(bot_msg, 50, data["token"])        # too fast -> bypass warning
    assert (await database.get_token_data(50))["verify"] is None
    await database.set_token_field(50, duration=time.time() - 1)
    await tok.verify_token(bot_msg, 50, data["token"])
    assert (await database.get_token_data(50))["verify"] == "True"

    await handler(None, Msg()); assert called == [1]

    await database.set_token_field(50, expires_at=time.time() - 1)   # expired -> new link, no crash
    await handler(None, Msg()); assert called == [1]


async def test_gate_lets_premium_and_admin_through(tok):
    called = []
    @tok.check_token_
    async def handler(c, m): called.append(m.from_user.id)
    await database.add_premium(60, 5)
    await handler(None, Msg(60)); await handler(None, Msg(222))      # 222 is admin (conftest)
    assert called == [60, 222]


async def test_wrong_token_issues_new_one(tok):
    await tok.get_token(Msg(), 70)
    old = (await database.get_token_data(70))["token"]
    await tok.verify_token(Msg(), 70, "WRONG")
    assert (await database.get_token_data(70))["token"] != old


async def test_expired_cleanup_runs(tok):
    await database.save_token_data(1, {"expires_at": time.time() - 1})
    assert await tok.expired_token_() == 1

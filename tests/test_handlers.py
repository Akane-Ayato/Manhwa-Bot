from types import SimpleNamespace as NS

import pyrogram
import pytest

import TG.cmds as cmds
import TG.callback as cb
from bot import parse_fsb
from Tools.base import AQueue, TaskCard
from Tools.db import database


class Msg:
    def __init__(self, text, uid=222, chat_id=None):
        self.text, self.from_user = text, NS(id=uid)
        self.chat = NS(id=chat_id or uid)
        self.replies = []

    async def reply_text(self, t, **kw):
        self.replies.append(t); return self

    reply = reply_text

    async def edit(self, t, **kw):
        self.replies.append(t); return self

    def stop_propagation(self):
        raise pyrogram.StopPropagation


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    async def send_message(*a, **k): return None
    monkeypatch.setattr(cmds.Bot.__class__, "send_message", lambda *a, **k: send_message(), raising=False)


async def test_add_premium_actually_adds_premium():
    client = NS(send_message=lambda *a, **k: _none())
    await cmds.add_handler(client, Msg("/add_premium 777 30"))
    plan = await database.premium_user(777)
    assert plan and plan["days"] == 30
    assert 777 not in cmds.Vars.ADMINS               # it used to promote the user to ADMIN instead


async def test_add_admin_and_usage_errors():
    client = NS(send_message=lambda *a, **k: _none())
    m = Msg("/add_admin 888")
    await cmds.add_handler(client, m)
    assert 888 in cmds.Vars.ADMINS
    cmds.Vars.ADMINS.remove(888)
    m2 = Msg("/add_premium abc")
    await cmds.add_handler(client, m2)
    assert any("Usage" in r for r in m2.replies)


async def test_non_admin_cannot_add_premium():
    await cmds.add_handler(NS(), Msg("/add_premium 5 5", uid=999))
    assert await database.premium_user(5) is None


async def _none(): return None


async def test_force_sub_gate(monkeypatch):
    client = NS(FSB=[("Chan", "chan")])
    monkeypatch.setattr(cmds.Vars, "FORCE_SUB_CHANNEL", "Chan:chan")
    sent = []

    async def not_joined(c, m): return ["btn"], []
    async def joined(c, m): return [], []
    async def reply_photo(*a, **k): sent.append(1)

    m = Msg("hello", uid=5); m.reply_photo = reply_photo
    monkeypatch.setattr(cmds, "check_fsb", not_joined)
    monkeypatch.setattr(cmds, "split_list", lambda x: [x])
    monkeypatch.setattr(cmds, "InlineKeyboardMarkup", lambda x: x)
    monkeypatch.setattr(cmds, "InlineKeyboardButton", lambda *a, **k: "b")
    with pytest.raises(pyrogram.StopPropagation):          # blocked: nothing else may run
        await cmds.on_private_message(client, m)
    assert sent == [1]

    monkeypatch.setattr(cmds, "check_fsb", joined)
    assert await cmds.on_private_message(client, m) is None   # joined: falls through to the real handler

    assert await cmds.on_private_message(client, Msg("x", uid=222)) is None   # admin bypasses the gate


async def test_force_sub_off_does_nothing(monkeypatch):
    monkeypatch.setattr(cmds.Vars, "FORCE_SUB_CHANNEL", "")
    assert await cmds.on_private_message(NS(FSB=[]), Msg("hi")) is None


def test_parse_fsb():
    assert parse_fsb("Join Us: my_chan , Other:-1001234:https://t.me/+x") == [
        ("Join Us", "my_chan"), ("Other", "-1001234", "https://t.me/+x")]
    assert parse_fsb("garbage, ok:chan") == [("ok", "chan")]      # one bad entry no longer disables all
    assert parse_fsb("") == []


async def test_cancel_only_by_owner(monkeypatch):
    q = AQueue()
    monkeypatch.setattr(cb, "queue", q)
    tid = await q.put(TaskCard(None, None, ["u"], 10, 10, 0, data_list=[{"title": "Chapter 1", "manga_title": "M"}], settings={"a": 1}))
    answers = []

    class Q:
        def __init__(self, uid):
            self.data = f"cql:{tid}"; self.from_user = NS(id=uid)
            self.message = NS(reply_to_message=None)
        async def answer(self, t=None, show_alert=False): answers.append(t)

    await cb.cl_handler(None, Q(11))                    # someone else
    assert q.qsize() == 1 and answers == ["This is not for you"]

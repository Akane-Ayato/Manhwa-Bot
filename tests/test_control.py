from types import SimpleNamespace as NS

import pytest

import TG.control as tc
from Tools import control
from config import Vars

OWNER, ADMIN, USER = 111, 222, 999


class M:
    def __init__(self, text, uid=OWNER):
        self.text, self.from_user = text, NS(id=uid)
        self.command = text.lstrip("/").split()
        self.replies, self.stopped = [], False

    async def reply_text(self, text, **kw):
        self.replies.append(text)

    def stop_propagation(self):
        self.stopped = True

    @property
    def last(self):
        return self.replies[-1]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(Vars, "OWNER", OWNER)
    monkeypatch.setattr(Vars, "ADMINS", [OWNER, ADMIN])
    control.BANNED.clear()
    control.STATE["maintenance"] = False
    yield
    control.BANNED.clear()
    control.STATE["maintenance"] = False


async def test_ban_blocks_user_but_not_admins_and_unban_restores():
    assert await control.ban(USER, "spam") == "banned"
    assert await control.ban(ADMIN) == "admins and the owner cannot be banned"
    m = M("hi", USER)
    await tc.gate_message(None, m)
    assert m.stopped and "banned" in m.last
    ok = M("hi", ADMIN)
    await tc.gate_message(None, ok)
    assert not ok.stopped
    await control.unban(USER)
    m2 = M("hi", USER)
    await tc.gate_message(None, m2)
    assert not m2.stopped


async def test_maintenance_blocks_everyone_but_owner_and_persists():
    await control.set_maintenance(True)
    for uid, blocked in [(USER, True), (ADMIN, True), (OWNER, False)]:
        m = M("hi", uid)
        await tc.gate_message(None, m)
        assert m.stopped is blocked
    control.STATE["maintenance"] = False
    await control.load()                                   # "restart": state comes back from the DB
    assert control.maintenance() is True


async def test_stop_command_modes():
    m = M("/stop")
    await tc.stop_cmd(None, m)
    assert control.maintenance() and m.stopped and "ON" in m.last
    m = M("/stop off")
    await tc.stop_cmd(None, m)
    assert not control.maintenance()


async def test_admin_add_remove_owner_rules_and_persistence():
    await tc.admin_cmd(None, M("/admin add 555"))
    assert 555 in Vars.ADMINS
    Vars.ADMINS.remove(555)
    await control.load()
    assert 555 in Vars.ADMINS                              # survived a "restart"
    m = M("/admin remove 111")
    await tc.admin_cmd(None, m)
    assert "cannot be removed" in m.last and OWNER in Vars.ADMINS
    m = M("/admin add 777", ADMIN)                         # plain admin may not add admins
    await tc.admin_cmd(None, m)
    assert "Only the owner" in m.last and 777 not in Vars.ADMINS
    await tc.admin_cmd(None, M("/admin ban 888 spammer", ADMIN))
    assert control.is_banned(888)
    m = M("/admin bans")
    await tc.admin_cmd(None, m)
    assert "888" in m.last and "spammer" in m.last


async def test_stats_text_has_the_bot_numbers():
    from Tools.db import database
    await database.ensure_user(1)
    text = control.stats_text(await control.bot_stats())
    assert "Users: 1" in text and "Series: 0" in text and "Channel queue" in text


async def test_admin_panel_without_args_and_owner_only_maintenance_button():
    m = M("/admin", ADMIN)
    await tc.admin_cmd(None, m)
    assert "Admin panel" in m.last
    labels = lambda owner: [b.text for r in tc.admin_panel_markup(owner).inline_keyboard for b in r]
    assert any("ᴀɪɴᴛᴇɴᴀɴᴄᴇ" in l for l in labels(True)) and not any("ᴀɪɴᴛᴇɴᴀɴᴄᴇ" in l for l in labels(False))

from types import SimpleNamespace as NS

import TG.guide as g
from config import Vars
from tests.test_control import M, OWNER, ADMIN, USER, clean  # noqa: F401


def test_every_registered_page_command_exists_and_roles_filter(monkeypatch):
    monkeypatch.setattr(Vars, "OWNER", OWNER)
    monkeypatch.setattr(Vars, "ADMINS", [OWNER, ADMIN])
    for key, (_, _, names) in g.PAGES.items():
        assert all(n in g.COMMANDS for n in names)
    assert g.role_of(USER) == "user" and g.role_of(ADMIN) == "admin" and g.role_of(OWNER) == "owner"
    user_buttons = [b.callback_data for r in g.home_markup("user").inline_keyboard for b in r]
    assert "gd_dl" in user_buttons and "gd_auto" not in user_buttons and "gd_own" not in user_buttons
    owner_buttons = [b.callback_data for r in g.home_markup("owner").inline_keyboard for b in r]
    assert {"gd_dl", "gd_auto", "gd_adm", "gd_own"} <= set(owner_buttons)


def test_pages_fit_in_a_message_and_hide_admin_commands_from_users():
    for role in ("user", "admin", "owner"):
        for key, (need, _, _) in g.PAGES.items():
            if g.allowed(role, need):
                text, _ = g.page(key, role)
                assert len(text) < 3800
    text, _ = g.page("dl", "user")
    assert "/queue" in text and "/add" not in text


async def test_help_with_command_name_and_unknown(monkeypatch):
    monkeypatch.setattr(Vars, "OWNER", OWNER)
    monkeypatch.setattr(Vars, "ADMINS", [OWNER, ADMIN])
    sent = []

    class Msg(M):
        async def reply_text(self, text, **kw):
            sent.append(text)
    await g.help_cmd(None, Msg("/help add", ADMIN))
    assert "/add" in sent[-1] and "batch" in sent[-1]
    await g.help_cmd(None, Msg("/help add", USER))              # admin command hidden from a normal user
    assert "No command" in sent[-1]

import pytest
from types import SimpleNamespace as NS

import Tools.settings_test as st
from tests.test_settings_applied import Rec, data_uri, set_owner, OWNER, UPD  # noqa: F401
from tests.test_settings_applied import env  # noqa: F401
from tests.test_pipeline import server, fast_retries  # noqa: F401
from tests.test_chmap import clean_state  # noqa: F401
import Tools.cworker as cw
import Tools.announce as announce


async def test_settings_test_runs_real_pipeline_and_reports(env, monkeypatch):
    bot, server, _ = env
    monkeypatch.setattr(st, "chservice", NS(check_channel=_ok_channel))
    monkeypatch.setattr(announce, "update_channel_for", _upd)
    await set_owner(file_name="Test {chapter_num}", caption="Cap {manga_title}", password="pw", type=["PDF"],
                    banner1=data_uri((9, 9, 200)), thumb=data_uri((0, 200, 0), (80, 80)), update_c=UPD,
                    before_post="hello", dump=-100999)
    rows = await st.run(OWNER, OWNER)
    names = {r[1]: r for r in rows}
    assert names["Upload"][0] == st.OK and names["File Name"][2] == "Test 1.pdf"
    assert names["Password"][0] == st.OK and names["Banner 1"][0] == st.OK and names["Thumbnail"][0] == st.OK
    assert names["Update Post"][0] == st.OK and names["Dump Channel"][0] == st.OK
    docs = [e for e in bot.events if e[0] == "doc"]
    assert docs and docs[0][1] == OWNER and docs[0][3] == "Cap Settings Test"           # went to the user's DM
    assert any(e[0] == "msg" and e[2] == "hello" for e in bot.events)                    # Before Post
    text = st.format_report(rows)
    assert "All checked settings work." in text


async def _ok_channel(chat):
    return "Some Channel", True


async def _upd(owner):
    return UPD


async def test_settings_test_flags_a_broken_banner_and_unreachable_channel(env, monkeypatch):
    bot, server, _ = env

    async def bad_channel(chat):
        raise RuntimeError("The bot is not an admin there")
    monkeypatch.setattr(st, "chservice", NS(check_channel=bad_channel))
    await set_owner(banner1="http://127.0.0.1:1/nothing.jpg", dump=-100999)
    rows = await st.run(OWNER, OWNER)
    names = {r[1]: r for r in rows}
    assert names["Banner 1"][0] == st.BAD and names["Dump Channel"][0] == st.BAD
    assert "problem(s)" in st.format_report(rows)

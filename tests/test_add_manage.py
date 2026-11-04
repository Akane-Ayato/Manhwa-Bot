import pytest

import TG.add_manage as am
import Tools.chmap as chmap
import Tools.chpoller as chpoller
import Tools.chservice as chservice
from Tools.chmap import MapError
from tests.test_chmap import CH, FakeChat, FakeWeb, add_doc, clean_state, use_web  # noqa: F401
from tests.test_chmap_cmds import Msg, Query, q


@pytest.fixture(autouse=True)
def env(monkeypatch, clean_state):
    monkeypatch.setattr(chservice, "Bot", FakeChat(CH))
    monkeypatch.setattr(am, "queue", clean_state.queue, raising=False)
    web = FakeWeb(titles=("Chapter 3", "Chapter 2", "Chapter 1"))
    web.sf = "18fx"
    use_web(monkeypatch, web)
    monkeypatch.setattr("Tools.chmap.Vars.MAP_SITES", ("18fx", "as"))
    return clean_state


def test_parse_add_ok_and_errors():
    assert am.parse_add(f"{CH} manga18fx https://x.com/manga/a batch") == (CH, "18fx", "https://x.com/manga/a", "batch", None)
    assert am.parse_add(f"{CH} Asura https://x.com/s/a-1234abcd LATEST My Title")[1:] == \
        ("as", "https://x.com/s/a-1234abcd", "latest", "My Title")
    for bad in ["", f"{CH} manga18fx https://x batch"[:20], f"12 manga18fx https://x.com batch",
                f"{CH} unknownsite https://x.com batch", f"{CH} asura x.com batch", f"{CH} asura https://x.com both"]:
        with pytest.raises(MapError):
            am.parse_add(bad)


def test_title_from_url():
    assert am.title_from_url("https://asuracomic.net/series/solo-leveling-a1b2c3d4") == "Solo Leveling"
    assert am.title_from_url("https://manga18fx.com/manga/my-hero/") == "My Hero"


async def test_add_without_args_shows_help():
    m = Msg("/add")
    await am.add_cmd(None, m)
    assert "Step 1 of 3" in m.last


async def test_add_batch_creates_mapping_and_queues(env):
    m = Msg(f"/add {CH} manga18fx https://www.mgeko.cc/manga/solo-leveling batch")   # fake 18fx site lives on this host
    await am.add_cmd(None, m)
    assert "Connected" in m.last and "Batch" in m.last
    doc = (await chmap.list_maps())[0]
    assert doc["mode"] == "batch" and doc["state"] == "batch" and doc["title"] == "Solo Leveling"
    assert len(env.queue.storage_data) == 2                       # lazy batch: only BATCH_DEPTH queued


async def test_add_wrong_site_for_url():
    m = Msg(f"/add {CH} asura https://www.mgeko.cc/manga/x batch")
    await am.add_cmd(None, m)
    assert "does not belong" in m.last


async def test_add_missing_rights_offers_retry_button_and_retry_works(monkeypatch, env):
    chat = FakeChat(CH, status="MEMBER") if "status" in FakeChat.__init__.__code__.co_varnames else None
    if chat is None:
        pytest.skip("FakeChat has no status option")
    monkeypatch.setattr(chservice, "Bot", chat)
    m = Msg(f"/add {CH} 18fx https://www.mgeko.cc/manga/x batch")
    await am.add_cmd(None, m)
    kb = m.replies[-1][1]["reply_markup"]
    token = kb.inline_keyboard[0][0].callback_data
    assert token.startswith("addr_")
    monkeypatch.setattr(chservice, "Bot", FakeChat(CH))          # rights given
    query = q(r"^addr_(\w+)$", token)
    await am.add_retry_cb(None, query)
    assert "Connected" in query.message.last


async def test_manage_list_and_open_remove_flow(env):
    doc = await add_doc()
    m = Msg("/manage")
    await am.manage_cmd(None, m)
    assert "Solo Leveling" in m.last
    buttons = [b.callback_data for row in m.replies[-1][1]["reply_markup"].inline_keyboard for b in row]
    assert f"chi_{doc['_id']}" in buttons
    query = q(r"^chi_(\d+)$", f"chi_{doc['_id']}")
    await am.open_cb(None, query)
    assert "watching for new chapters" in query.message.last
    assert await chservice.remove_mapping(doc["_id"])
    assert await chmap.list_maps() == []


async def test_failed_chapter_retry_and_skip_buttons(env):
    doc = await add_doc(posted=("1",))
    for _ in range(3):
        await chpoller.add_failure(doc["_id"], "2", "Chapter 2", "boom")
    query = q(r"^chs_(\d+)$", f"chs_{doc['_id']}")
    await am.skip_failed_cb(None, query)
    assert "2" in (await chmap.get_map(doc["_id"]))["posted"] and not await chpoller.list_failures(doc["_id"])
    await chpoller.add_failure(doc["_id"], "3", "Chapter 3", "boom")
    await am.retry_failed_cb(None, q(r"^chf_(\d+)$", f"chf_{doc['_id']}"))
    assert not await chpoller.list_failures(doc["_id"])


async def test_guided_add_wizard_steps_and_listen_flow(env):
    m = Msg("/add")
    await am.add_cmd(None, m)
    datas = [b.callback_data for row in m.replies[-1][1]["reply_markup"].inline_keyboard for b in row]
    assert "adds_18fx" in datas and "adds_as" in datas

    query = q(r"^adds_(\w+)$", "adds_18fx")
    await am.add_source_cb(None, query)
    assert "Step 2" in query.message.last

    class Client:                       # the admin "types" the channel id and link
        async def listen(self, **kw):
            return Msg(f"{CH} https://www.mgeko.cc/manga/solo-leveling")
    query = q(r"^addm_(\w+)_(batch|latest)$", "addm_18fx_latest")
    await am.add_mode_cb(Client(), query)
    docs = await chmap.list_maps()
    assert len(docs) == 1 and docs[0]["mode"] == "latest"


async def test_hub_buttons_switch_batch_rename_and_change_channel(env, monkeypatch):
    doc = await add_doc(posted=("1",), site="18fx")
    markup = am.info_markup(doc)
    datas = [b.callback_data for r in markup.inline_keyboard for b in r]
    assert {f"chbb_{doc['_id']}", f"chnm_{doc['_id']}", f"chcc_{doc['_id']}"} <= set(datas)

    res = await chservice.start_batch(doc["_id"])                      # upload every missing chapter
    assert res["total"] == 2 and res["queued"] == 2                     # chapters 2 and 3 (1 already posted)
    got = await chmap.get_map(doc["_id"])
    assert got["state"] == "batch" and got["mode"] == "batch"
    assert f"chbs_{doc['_id']}" in [b.callback_data for r in am.info_markup(got).inline_keyboard for b in r]

    await chservice.stop_batch(doc["_id"])
    got = await chmap.get_map(doc["_id"])
    assert got["state"] == "live" and got["mode"] == "latest" and not env.queue.storage_data

    class Chat(FakeChat):
        async def get_chat(self, cid): return NS(id=cid, title="New Channel", type=NS(name="CHANNEL"))
    from types import SimpleNamespace as NS
    title = await chservice.change_channel(doc["_id"], -1009999999999, Chat(-1009999999999))
    got = await chmap.get_map(doc["_id"])
    assert title == "New Channel" and got["channel_id"] == -1009999999999 and got["invite_link"]


async def test_hub_opens_from_settings_button_and_lists(env):
    await add_doc()
    query = q(r"^mm_home$", "mm_home")
    await am.hub_cb(None, query)
    assert "Solo Leveling" in query.message.last
    labels = [b.callback_data for r in query.message.replies[-1][1]["reply_markup"].inline_keyboard for b in r]
    assert "adds_home" in labels and "target_channel" in labels


async def test_nothing_missing_is_a_clear_error(env):
    doc = await add_doc(posted=("1", "2", "3"))
    with pytest.raises(MapError):
        await chservice.start_batch(doc["_id"])

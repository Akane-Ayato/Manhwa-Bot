"""Handlers of TG/chmap_cmds.py called directly with fake messages."""
from types import SimpleNamespace as NS

import pytest

import TG.chmap_cmds as cc
import Tools.chmap as chmap
import Tools.chpoller as chpoller
import Tools.chservice as chservice
from Tools.base import AQueue
from config import Vars
from tests.test_chmap import FakeWeb, FakeChat, add_doc, use_web, clean_state, CH  # noqa: F401


class Msg:
    def __init__(self, text, uid=222, reply_to=None):
        self.text, self.from_user, self.reply_to_message = text, NS(id=uid), reply_to
        self.command = text.split()[0].lstrip("/").split("@")[0:1]
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append((text, kw)); return self

    async def edit(self, text, **kw):
        self.replies.append((text, kw)); return self

    edit_text = edit

    @property
    def last(self):
        return self.replies[-1][0]


class Query:
    def __init__(self, data_match, uid=222):
        self.matches, self.from_user, self.answers = [data_match], NS(id=uid), []
        self.message = Msg("x")

    async def answer(self, text="", **kw):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        return await self.message.edit_text(text, **kw)

    edit_message_caption = edit_message_text


import re


def q(pattern, data, uid=222):
    return Query(re.match(pattern, data), uid)


@pytest.fixture(autouse=True)
def admin_env(monkeypatch, clean_state):
    monkeypatch.setattr(chservice, "Bot", FakeChat(CH))
    monkeypatch.setattr(cc, "queue", clean_state.queue)
    use_web(monkeypatch, FakeWeb())
    return clean_state


def test_admin_filter():
    assert cc._is_admin(None, None, NS(from_user=NS(id=222)))        # ADMINS from the test env
    assert not cc._is_admin(None, None, NS(from_user=NS(id=999)))
    assert not cc._is_admin(None, None, NS(from_user=None))


async def test_ch_map_without_args_shows_help_with_sites():
    m = Msg("/ch_map")
    await cc.ch_map_cmd(None, m)
    assert "/ch_map &lt;manga name&gt;" in m.last and "mgeko" in m.last


async def test_ch_map_success_message_and_db_row(monkeypatch):
    m = Msg(f"/ch_map Solo Leveling https://www.mgeko.cc/manga/solo/ {CH}")
    await cc.ch_map_cmd(None, m)
    assert "Mapped #1" in m.last and "Solo Leveling" in m.last and "3 chapters" in m.last
    assert "Only <b>new</b>" in m.last and "created" in m.last
    assert len(await chmap.list_maps()) == 1


async def test_ch_map_reports_validation_errors_without_saving():
    for text, frag in [
        (f"/ch_map Solo https://unknown.example/a {CH}", "Unsupported site"),
        ("/ch_map Solo https://www.mgeko.cc/x 12345", "Channel id"),
        ("/ch_map Solo", "3 parts"),
    ]:
        m = Msg(text)
        await cc.ch_map_cmd(None, m)
        assert frag in m.last
    assert await chmap.list_maps() == []


async def test_ch_map_last_flag_queues_newest(admin_env, monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=("Chapter 4", "Chapter 3", "Chapter 2", "Chapter 1")))
    m = Msg(f"/ch_map --last 2 Solo https://www.mgeko.cc/manga/solo/ {CH}")
    await cc.ch_map_cmd(None, m)
    assert "2 chapter(s) queued" in m.last and admin_env.queue.qsize() == 2


async def test_list_paginates_and_shows_channel_and_last_chapter():
    for i in range(30):
        await add_doc(series_url=f"https://www.mgeko.cc/manga/{i}/", title=f"Manhwa {i}", channel_title=f"Chan {i % 3}")
    m = Msg("/ch_list")
    await cc.ch_list_cmd(None, m)
    text, kw = m.replies[0]
    assert "Page 1/3" in text and "Manhwa 0" in text and "Chan 0" in text and "last <b>3</b>" in text
    assert "Manhwa 12" not in text and len(text) < 4000
    labels = [b.text for row in kw["reply_markup"].inline_keyboard for b in row]
    assert "Nᴇxᴛ ▸" in labels and not any("Prᴇᴠ" in l for l in labels)

    query = q(cc.ch_list_cb.__name__ and r"^chl_(\d+)_(\w+)$", "chl_3_all")
    await cc.ch_list_cb(None, query)
    assert "Page 3/3" in query.message.last and "Manhwa 29" in query.message.last


async def test_list_empty_and_status_filter():
    m = Msg("/ch_list")
    await cc.ch_list_cmd(None, m)
    assert "Nothing connected yet" in m.last
    doc = await add_doc()
    await chservice.set_status(doc["_id"], "paused")
    m = Msg("/ch_list paused")
    await cc.ch_list_cmd(None, m)
    assert "Solo Leveling" in m.last
    m = Msg("/ch_list error")
    await cc.ch_list_cmd(None, m)
    assert "Nothing connected yet" in m.last


async def test_info_pause_resume_buttons_and_commands():
    doc = await add_doc()
    m = Msg(f"/ch_info {doc['_id']}")
    await cc.ch_info_cmd(None, m)
    assert "Solo Leveling" in m.last and "My Channel" in m.last and "https://t.me/+abc" in m.last
    qy = q(r"^ch([pr])_(\d+)$", f"chp_{doc['_id']}")
    await cc.ch_pause_cb(None, qy)
    assert (await chmap.get_map(doc["_id"]))["status"] == "paused" and qy.answers == ["Paused"]
    m = Msg(f"/ch_resume {doc['_id']}")
    await cc.ch_pause_resume_cmd(None, m)
    assert (await chmap.get_map(doc["_id"]))["status"] == "active" and "Resumed" in m.last
    m = Msg("/ch_pause all")
    await cc.ch_pause_resume_cmd(None, m)
    assert "Paused 1" in m.last


async def test_ambiguous_name_asks_for_id_and_unknown_is_reported():
    await add_doc(title="Solo Leveling")
    await add_doc(series_url="https://www.mgeko.cc/manga/s2/", title="Solo Leveling Ragnarok")
    m = Msg("/ch_info solo")
    await cc.ch_info_cmd(None, m)
    assert "2 matches" in m.last
    m = Msg("/ch_info nothing")
    await cc.ch_info_cmd(None, m)
    assert "No mapping found" in m.last
    m = Msg("/ch_info")
    await cc.ch_info_cmd(None, m)
    assert "Give a mapping id" in m.last


async def test_remove_needs_confirmation():
    doc = await add_doc()
    m = Msg(f"/ch_remove {doc['_id']}")
    await cc.ch_remove_cmd(None, m)
    assert "Remove" in m.last and await chmap.get_map(doc["_id"])          # nothing deleted yet
    qy = q(r"^chry_(\d+)$", f"chry_{doc['_id']}")
    await cc.ch_remove_yes_cb(None, qy)
    assert await chmap.get_map(doc["_id"]) is None and "Removed" in qy.message.last


async def test_check_one_all_and_failed_retry_skip(admin_env, monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=("Chapter 5", "Chapter 4", "Chapter 3")))
    doc = await add_doc(posted=("3",))
    m = Msg(f"/ch_check {doc['_id']}")
    await cc.ch_check_cmd(None, m)
    assert "2 new chapter(s) queued" in m.last
    admin_env.queue.storage_data.clear()

    for _ in range(Vars.RETRY_LIMIT):
        await chpoller.add_failure(doc["_id"], "4", "Chapter 4", "boom")
    m = Msg("/ch_failed")
    await cc.ch_failed_cmd(None, m)
    assert "1 failed" in m.last and "boom" in m.last
    m = Msg(f"/ch_skip {doc['_id']} 4")
    await cc.ch_skip_cmd(None, m)
    got = await chmap.get_map(doc["_id"])
    assert "4" in got["posted"] and got["next_check"] == 0 and "boom" not in (await cc_failed_text())
    await chpoller.add_failure(doc["_id"], "5", "Chapter 5", "x")
    m = Msg(f"/ch_retry {doc['_id']}")
    await cc.ch_retry_cmd(None, m)
    assert "Cleared 1" in m.last
    m = Msg("/ch_check")
    await cc.ch_check_cmd(None, m)
    assert "Checked 1" in m.last


async def cc_failed_text():
    m = Msg("/ch_failed")
    await cc.ch_failed_cmd(None, m)
    return m.last


async def test_edit_name_url_channel_and_bad_values(monkeypatch):
    doc = await add_doc()
    m = Msg(f"/ch_edit {doc['_id']} name New Name Here")
    await cc.ch_edit_cmd(None, m)
    assert (await chmap.get_map(doc["_id"]))["title"] == "New Name Here"
    m = Msg(f"/ch_edit {doc['_id']} url https://nope.example/x")
    await cc.ch_edit_cmd(None, m)
    assert "Unsupported site" in m.last
    m = Msg(f"/ch_edit {doc['_id']} channel -1009999999999")
    monkeypatch.setattr(chservice, "Bot", FakeChat(-1009999999999, title="Other"))
    await cc.ch_edit_cmd(None, m)
    got = await chmap.get_map(doc["_id"])
    assert got["channel_id"] == -1009999999999 and got["channel_title"] == "Other" and got["invite_link"] == "https://t.me/+JOIN"
    m = Msg(f"/ch_edit {doc['_id']} channel 123")
    await cc.ch_edit_cmd(None, m)
    assert "Channel id must look like" in m.last


async def test_import_from_pasted_lines_and_export_file():
    text = (f"/ch_import\n# list\nAlpha https://www.mgeko.cc/manga/a/ {CH}\nBeta https://www.mgeko.cc/manga/b/ {CH}\n"
            "bad line here")
    m = Msg(text)
    await cc.ch_import_cmd(NS(), m)
    assert "Added 2" in m.last and "failed 1" in m.last
    assert len(await chmap.list_maps()) == 2

    sent = {}

    class Doc(Msg):
        async def reply_document(self, data, caption=None, **kw):
            sent["name"], sent["body"], sent["caption"] = data.name, data.getvalue().decode(), caption

    d = Doc("/ch_export")
    await cc.ch_export_cmd(None, d)
    assert sent["name"] == "channel_maps.txt" and "Alpha https://www.mgeko.cc/manga/a/" in sent["body"] and "2 mapping" in sent["caption"]


async def test_import_without_content_explains_format():
    m = Msg("/ch_import")
    await cc.ch_import_cmd(NS(), m)
    assert "reply to it" in m.last


async def test_stats_and_sites_and_queue_panel():
    await add_doc()
    m = Msg("/ch_stats")
    await cc.ch_stats_cmd(None, m)
    assert "Mappings: 1" in m.last and "Poll every" in m.last
    m = Msg("/ch_sites")
    await cc.ch_sites_cmd(None, m)
    assert "mgeko" in m.last and "1 mapped" in m.last


async def test_queue_command_text_shows_auto_section_with_progress_for_admins(admin_env, monkeypatch):
    import TG.queue as tq
    monkeypatch.setattr(tq, "queue", admin_env.queue)
    from tests.test_chmap import _auto_card
    card = _auto_card(1, "7")
    card.target_title = "My Channel"
    await admin_env.queue.put(card, True)
    running, _ = await admin_env.queue.get(1)
    running.progress.set_stage("Downloading", total=40, unit="pages")
    running.progress.update(10)
    await admin_env.queue.put(_auto_card(2, "9", user=-1002), True)
    text = await tq.get_queue_text(222)
    assert "Channel auto-posts" in text and "▰" in text and "10/40 pages" in text and "1 waiting" in text
    plain = await tq.get_queue_text(555)                                  # normal user never sees channel jobs
    assert "Channel auto-posts" not in plain

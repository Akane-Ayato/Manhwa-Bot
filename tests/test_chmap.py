"""Channel mapping: parsing, DB layer, poller, queue rules, worker hooks, commands."""
import asyncio
import os
import time
from types import SimpleNamespace as NS

import pytest

import Tools.chmap as chmap
import Tools.chpoller as chpoller
import Tools.chservice as chservice
import Tools.cworker as cw
import Tools.announce as announce
from Tools.base import AQueue, TaskCard, queue as global_queue
from Tools.chmap import MapError
from Tools.db import database
from config import Vars
from tests.test_pipeline import Handler, server, fast_retries  # noqa: F401  (fixtures)
import tests.test_worker_e2e as e2e

CH = -1001234567890


# ------------------------------------------------------------------ helpers ---
class FakeWeb:
    """Scraper stand-in: chapters newest-first like the real sites."""
    sf, url, cs = "mgeko", "https://www.mgeko.cc/", False
    __name__ = "FakeWeb"

    def __init__(self, titles=("Chapter 3", "Chapter 2", "Chapter 1"), server_url=None, fail=False, no_pics=False):
        self.titles, self.fail, self.no_pics, self.server = list(titles), fail, no_pics, server_url
        self.scrapes = 0

    async def get_chapters(self, data, page=1):
        self.scrapes += 1
        if self.fail:
            raise RuntimeError("site exploded")
        return {**data, "chapters": self.titles}

    def iter_chapters(self, data, page=1):
        return [{"title": t, "url": f"https://www.mgeko.cc/c/{i}", "manga_title": data["title"], "poster": "http://cover/x.jpg"}
                for i, t in enumerate(data["chapters"])]

    async def get_pictures(self, url, data=None):
        if self.no_pics:
            return []
        base = self.server or "http://127.0.0.1:1"
        return [f"{base}/ok/{i}" for i in range(1, 4)]


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    chpoller.reset_gates()
    q = AQueue()
    monkeypatch.setattr(chpoller, "queue", q)
    monkeypatch.setattr(cw, "queue", q)
    monkeypatch.setattr(Vars, "SITE_DELAY", 0)
    monkeypatch.setattr(Vars, "UPDATE_CHANNEL", None)
    alerts = []

    async def fake_alert(text):
        alerts.append(text)
    monkeypatch.setattr(chpoller, "notify_admin", fake_alert)
    return NS(queue=q, alerts=alerts)


def use_web(monkeypatch, web):
    monkeypatch.setattr(chpoller, "_site_of", lambda doc: web)
    import TG.storage as st
    monkeypatch.setattr(st, "web_data", {" Mgeko ": web}, raising=False)
    monkeypatch.setattr(st, "get_webs", lambda sf: web if sf == web.sf else None)


async def add_doc(posted=("1", "2", "3"), **kw):
    base = dict(title="Solo Leveling", site="mgeko", series_url="https://www.mgeko.cc/manga/solo/", channel_id=CH,
                channel_title="My Channel", owner_id=222, last_chapter=posted[-1] if posted else None,
                posted=list(posted), invite_link="https://t.me/+abc")
    base.update(kw)
    return await chmap.add_map(**base)


# ------------------------------------------------------------------ parsing ---
def test_parse_name_with_spaces_dashes_and_quotes():
    name, url, chat = chmap.parse_map_args(f'The Beginning After The End - Remake https://mgeko.cc/manga/tbate/ {CH}')
    assert name == "The Beginning After The End - Remake" and url == "https://mgeko.cc/manga/tbate/" and chat == CH


@pytest.mark.parametrize("text,fragment", [
    ("only two", "3 parts"),
    ("Name https://x.com/a 12345", "Channel id"),
    (f"Name notaurl {CH}", "URL"),
    (f"https://x.com/a {CH}", "3 parts"),
])
def test_parse_rejects_bad_input(text, fragment):
    with pytest.raises(MapError) as err:
        chmap.parse_map_args(text)
    assert fragment in str(err.value)


def test_import_lines_skip_comments_and_report_errors():
    text = f"# my list\n\nA https://a.com/x {CH}\nbroken line\nB https://b.com/y -1009999999999\n"
    ok, bad = chmap.parse_import_lines(text)
    assert [o[0] for o in ok] == ["A", "B"] and len(bad) == 1 and bad[0][0] == 4


def test_site_detection_uses_domain_and_allow_list(monkeypatch):
    web = FakeWeb()
    data = {" Mgeko ": web, " Other ": NS(sf="zzz", url="https://other.com/")}
    assert chmap.detect_site("https://mgeko.cc/manga/x/", {" Mgeko ": NS(sf="mgeko", url="https://www.mgeko.cc/")}) is not None
    assert chmap.detect_site("https://www.mgeko.cc/manga/x/", data) is web
    assert chmap.detect_site("https://other.com/a", data) is None       # not in MAP_SITES
    assert chmap.detect_site("https://evil.com/mgeko.cc", data) is None  # domain, not substring
    assert chmap.detect_site("not a url", data) is None


@pytest.mark.parametrize("title,key", [
    ("Chapter 10", "10"), ("Chapter 10.50", "10.5"), ("123-eng-li", "123"), ("Ch. 7: The/End?", "7"), ("Prologue", None),
])
def test_chapter_key(title, key):
    assert chmap.chapter_key(title) == key


def test_new_chapters_sorted_deduped_and_skips_posted():
    chapters = [{"title": t} for t in ["Chapter 10.5", "Chapter 10", "Chapter 10 (re-up)", "Chapter 2", "Special"]]
    result = chmap.new_chapters(chapters, ["2"])
    assert [c["_key"] for c in result] == ["10", "10.5"]     # ascending, 2 already posted, dup + unnumbered dropped


# ----------------------------------------------------------------- database ---
async def test_ids_unique_constraint_and_lookup():
    a = await add_doc()
    b = await add_doc(series_url="https://www.mgeko.cc/manga/other/", title="Other Manhwa")
    assert (a["_id"], b["_id"]) == (1, 2)
    with pytest.raises(MapError):
        await add_doc()                                      # same url + channel
    assert [d["_id"] for d in await chmap.find_maps("2")] == [2]
    assert [d["_id"] for d in await chmap.find_maps("solo")] == [1]
    assert await chmap.find_maps("nothing") == []
    assert (await chmap.count_maps())["active"] == 2


async def test_record_posted_tracks_last_and_count():
    doc = await add_doc(posted=("1",))
    await chmap.record_posted(doc["_id"], "5")
    await chmap.record_posted(doc["_id"], "4")
    await chmap.record_posted(doc["_id"], "5")               # duplicate ignored
    got = await chmap.get_map(doc["_id"])
    assert got["posted"] == ["1", "5", "4"] and got["last_chapter"] == "5" and got["posted_count"] == 3


async def test_due_maps_and_backoff():
    doc = await add_doc()
    assert [d["_id"] for d in await chmap.due_maps()] == [doc["_id"]]
    await chmap.mark_checked(doc["_id"], ok=True)
    assert await chmap.due_maps() == []
    await chmap.mark_checked(doc["_id"], ok=False, error="boom")
    got = await chmap.get_map(doc["_id"])
    assert got["fail_count"] == 1 and got["last_error"] == "boom" and got["next_check"] > time.time() + Vars.POLL_MINUTES * 60
    await chmap.update_map(doc["_id"], status="paused", next_check=0)
    assert await chmap.due_maps() == []                      # paused maps are never due


# ------------------------------------------------------------------- poller ---
async def test_baseline_means_no_posts(clean_state, monkeypatch):
    use_web(monkeypatch, FakeWeb())
    doc = await add_doc()
    res = await chpoller.check_map(doc)
    assert res == {"queued": 0, "error": None, "skipped": None} and clean_state.queue.qsize() == 0


async def test_new_chapter_is_queued_as_auto_task_for_the_channel(clean_state, monkeypatch):
    web = FakeWeb(titles=("Chapter 5", "Chapter 4", "Chapter 3", "Chapter 2", "Chapter 1"))
    use_web(monkeypatch, web)
    await database.save_settings(222, {"caption": "X"}) if hasattr(database, "save_settings") else None
    doc = await add_doc()
    res = await chpoller.check_map(doc)
    assert res["queued"] == 2
    cards = [t for t, _ in clean_state.queue.storage_data.values()]
    assert {c.chapter_key for c in cards} == {"4", "5"}
    c = cards[0]
    assert c.kind == "auto" and c.user_id == CH and c.chat_id == CH and c.owner_id == 222 and c.map_id == doc["_id"]
    assert c.sts is None and c.on_success and c.on_failure
    assert c.processsing is None                                            # nothing downloaded until a worker takes it
    # a second check while they are still queued must not double-queue
    again = await chpoller.check_map(await chmap.get_map(doc["_id"]))
    assert again["queued"] == 0 and clean_state.queue.qsize() == 2
    # channel ids never become users
    assert await database.users.find_one({"_id": str(CH)}) is None


async def test_burst_of_new_chapters_pauses_mapping(clean_state, monkeypatch):
    titles = tuple(f"Chapter {i}" for i in range(30, 0, -1))
    use_web(monkeypatch, FakeWeb(titles=titles))
    doc = await add_doc(posted=("1",))
    res = await chpoller.check_map(doc)
    assert res["error"] == "burst limit" and clean_state.queue.qsize() == 0
    assert (await chmap.get_map(doc["_id"]))["status"] == "error" and clean_state.alerts


async def test_site_error_counts_and_opens_circuit_breaker(clean_state, monkeypatch):
    web = FakeWeb(fail=True)
    use_web(monkeypatch, web)
    doc = await add_doc()
    for _ in range(chpoller.SITE_FAIL_LIMIT):
        res = await chpoller.check_map(await chmap.get_map(doc["_id"]), force=False)
        if res["skipped"]:
            break
    assert chpoller.gate_for("mgeko").is_down and len(clean_state.alerts) == 1
    scrapes = web.scrapes
    res = await chpoller.check_map(await chmap.get_map(doc["_id"]))
    assert res["skipped"] and web.scrapes == scrapes         # no request while the breaker is open
    assert (await chmap.get_map(doc["_id"]))["fail_count"] >= 1


async def test_empty_chapter_list_is_an_error_not_no_updates(clean_state, monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=()))
    doc = await add_doc()
    res = await chpoller.check_map(doc)
    assert "no chapters" in res["error"]


async def test_failed_chapter_blocks_later_ones_until_retry(clean_state, monkeypatch):
    web = FakeWeb(titles=("Chapter 5", "Chapter 4", "Chapter 3"))
    use_web(monkeypatch, web)
    doc = await add_doc(posted=("3",))
    for _ in range(Vars.RETRY_LIMIT):
        await chpoller.add_failure(doc["_id"], "4", "Chapter 4", "boom")
    res = await chpoller.check_map(await chmap.get_map(doc["_id"]))
    assert res["queued"] == 0 and clean_state.queue.qsize() == 0       # 4 failed -> 5 must wait (channel order)
    assert await chpoller.reset_failures(doc["_id"]) == 1
    res = await chpoller.check_map(await chmap.get_map(doc["_id"]))
    assert res["queued"] == 2


async def test_no_pictures_counts_as_failure_and_alerts_once(clean_state, monkeypatch):
    web = FakeWeb(titles=("Chapter 4", "Chapter 3"), no_pics=True)
    use_web(monkeypatch, web)
    doc = await add_doc(posted=("3",))
    for _ in range(Vars.RETRY_LIMIT + 2):
        await chpoller.check_map(await chmap.get_map(doc["_id"]))
    assert await chpoller.failure_attempts(doc["_id"], "4") == Vars.RETRY_LIMIT   # stops retrying at the limit
    assert len(clean_state.alerts) == 1


async def test_poll_once_groups_by_site_and_respects_pause(clean_state, monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=("Chapter 4", "Chapter 3", "Chapter 2", "Chapter 1")))
    a = await add_doc(posted=("1", "2", "3"))
    b = await add_doc(series_url="https://www.mgeko.cc/manga/b/", posted=("1", "2", "3"), title="B")
    await chservice.set_status(b["_id"], "paused")
    stats = await chpoller.poll_once()
    assert stats["checked"] == 1 and stats["queued"] == 1
    assert (await chpoller.poll_once())["checked"] == 0                  # nothing is due a second time


# -------------------------------------------------------------------- queue ---
def _auto_card(map_id, key, user=CH, kind="auto"):
    card = TaskCard(FakeWeb(), None, ["u"], user, user, 0,
                    data_list=[{"title": f"Chapter {key}", "manga_title": "M", "url": "u"}],
                    settings={"_auto": True}, kind=kind)
    card.map_id, card.chapter_key = map_id, key
    return card


async def test_queue_orders_chapters_per_channel_and_limits_auto_parallelism(monkeypatch):
    monkeypatch.setattr(Vars, "AUTO_MAX_PARALLEL", 2)
    q = AQueue()
    for key in ("12", "3", "7"):
        await q.put(_auto_card(1, key), True)
    first, _ = await q.get(1)
    assert first.chapter_key == "3"                       # ascending inside one channel
    assert q.get_available_tasks() is None                # same channel is busy -> next waits (order!)
    for i, ch in enumerate((-1002, -1003), start=10):
        await q.put(_auto_card(i, "1", user=ch), True)
    second, _ = await q.get(2)
    assert q.auto_running() == 2
    user_card = _auto_card(99, "1", user=555, kind="user"); user_card.priority = 0
    await q.put(user_card, False)
    third = q.get_available_tasks()
    assert third and third[0] is user_card                # auto lane is full: a normal user task still runs
    assert await database.users.find_one({"_id": str(CH)}) is None


async def test_delete_map_tasks_and_has_map_chapter():
    q = AQueue()
    await q.put(_auto_card(1, "1"), True)
    await q.put(_auto_card(2, "1", user=-1002), True)
    assert q.has_map_chapter(1, "1") and not q.has_map_chapter(1, "2")
    assert await q.delete_map_tasks(1) == 1 and q.qsize() == 1


# ----------------------------------------------------------- worker + hooks ---
@pytest.fixture
def worker_env(monkeypatch, tmp_path, server, clean_state):
    monkeypatch.chdir(tmp_path)
    bot = e2e.FakeBot()
    monkeypatch.setattr(cw, "Bot", bot)
    monkeypatch.setattr(cw.Vars, "CONSTANT_DUMP_CHANNEL", None)
    monkeypatch.setattr(cw.Vars, "LOG_CHANNEL", None)
    targets = []

    class U:
        async def upload_to_targets_channels(self, *a, **k): targets.append(k)
    monkeypatch.setattr(cw, "Uploader", U)
    monkeypatch.setattr(announce, "Bot", bot)
    return bot, targets, server


async def test_auto_task_posts_to_channel_records_chapter_and_announces(worker_env, clean_state, monkeypatch):
    bot, targets, server = worker_env
    web = FakeWeb(titles=("Chapter 4", "Chapter 3"), server_url=server)
    use_web(monkeypatch, web)
    monkeypatch.setattr(Vars, "UPDATE_CHANNEL", -100777)
    monkeypatch.setattr(announce.Vars, "UPDATE_CHANNEL", -100777)
    sent = []

    async def send_message(chat, text, **kw):
        sent.append((chat, text, kw)); return NS(copy=lambda *a, **k: e2e._n())
    bot.send_message = send_message
    doc = await add_doc(posted=("3",))
    assert (await chpoller.check_map(doc))["queued"] == 1

    card, _ = await clean_state.queue.get(1)
    stages = []
    orig = card.progress.set_stage
    card.progress.set_stage = lambda stage, *a, **k: (stages.append(stage), orig(stage, *a, **k))[1]
    await cw.send_manga_chapter(card)
    await clean_state.queue.task_done(card)
    import os
    assert not os.path.exists(f"Process/{card.tasks_id}")        # chapter deleted from disk right after upload

    assert [c for c, *_ in [(g[0].chat.id,) for g in bot.groups]] == [CH]          # uploaded to the CHANNEL
    assert not targets                                                               # user target-channel feature skipped
    got = await chmap.get_map(doc["_id"])
    assert got["posted"][-1] == "4" and got["last_chapter"] == "4" and got["posted_count"] == 1
    assert "Building" in stages and "Uploading" in stages and card.progress.stage == "Posted"
    announced = [s for s in sent if s[0] == -100777]
    assert announced and "Solo Leveling" in announced[0][1] and announced[0][2]["reply_markup"] is not None
    assert not [s for s in sent if s[0] == CH]                                       # nothing but the PDF in the channel
    assert (await chpoller.check_map(await chmap.get_map(doc["_id"])))["queued"] == 0   # not posted twice


async def test_auto_task_failure_never_posts_errors_in_channel_and_counts_attempt(worker_env, clean_state, monkeypatch):
    bot, _, server = worker_env
    use_web(monkeypatch, FakeWeb(titles=("Chapter 4", "Chapter 3"), server_url=server))
    sent = []

    async def send_message(chat, text, **kw):
        sent.append((chat, text)); return NS(copy=lambda *a, **k: e2e._n())
    bot.send_message = send_message
    doc = await add_doc(posted=("3",))
    await chpoller.check_map(doc)
    card, _ = await clean_state.queue.get(1)
    card.picturesList = [f"{server}/missing"]                # every page 404s
    await cw.send_manga_chapter(card)
    await clean_state.queue.task_done(card)

    assert not bot.groups
    assert not [s for s in sent if s[0] == CH]               # never an error text inside the public channel
    assert await chpoller.failure_attempts(doc["_id"], "4") == 1
    assert "4" not in (await chmap.get_map(doc["_id"]))["posted"]      # NOT marked posted -> will be retried


async def test_worker_loop_reports_failure_when_task_has_no_pictures(clean_state, monkeypatch):
    doc = await add_doc()
    card = _auto_card(doc["_id"], "9")
    card.picturesList = []
    seen = []

    async def on_failure(c, reason): seen.append(reason)
    card.on_failure = on_failure
    await clean_state.queue.put(card, True)

    async def fake_send_error(*a, **k): return None
    monkeypatch.setattr(cw, "send_error", fake_send_error)
    task = asyncio.create_task(cw.worker(1))
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.05)
    task.cancel()
    assert seen and clean_state.queue.ongoing_tasks == {}     # failure reported once, slot released


# ----------------------------------------------------------------- progress ---
def test_progress_bar_and_lines():
    from Tools.progress import Progress, bar, fmt_eta, fmt_size
    assert bar(0) == "▱" * 10 and bar(100) == "▰" * 10 and bar(55) == "▰▰▰▰▰▰▱▱▱▱"[:10]
    assert bar(-5) == "▱" * 10 and bar(500) == "▰" * 10
    assert fmt_size(1536) == "1.5 KB" and fmt_eta(75) == "1m 15s" and fmt_eta(None) == "--"
    p = Progress()
    p.set_stage("Downloading", total=50, unit="pages")
    p.update(25)
    assert "50%" in p.line() and "25/50 pages" in p.line()
    p.set_stage("Posted")
    assert p.percent == 100


async def test_download_reports_progress(server, tmp_path):
    from Tools.img2pdf import download_and_convert_images
    seen = []
    await download_and_convert_images([f"{server}/ok/{i}" for i in range(1, 4)], str(tmp_path / "p"), server,
                                      on_progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


async def test_status_message_edits_are_throttled_and_never_raise():
    from Tools.progress import push
    edits = []

    class Sts:
        async def edit(self, text, **kw): edits.append(text)

    card = _auto_card(1, "1"); card.sts = Sts()
    card.progress.set_stage("Downloading", total=10, unit="pages")
    await push(card, force=True)
    card.progress.update(5)
    await push(card)                                         # within 3 s -> skipped
    assert len(edits) == 1 and "0%" in edits[0]

    class Broken:
        async def edit(self, *a, **k): raise RuntimeError("MESSAGE_ID_INVALID")
    card.sts = Broken()
    await push(card, force=True)                             # must not raise


# ----------------------------------------------------------------- announce ---
def test_announce_buttons_have_red_join_request_style():
    markup = announce.build_markup("https://t.me/+abc", "https://t.me/c/1/2")
    join = markup.inline_keyboard[0][0]
    assert join.url == "https://t.me/+abc"
    enums = pytest.importorskip("pyrogram.enums")
    if not hasattr(enums, "ButtonStyle"):                      # pyrofork: plain button, nothing breaks
        assert join.text.startswith("◉")
    else:
        assert join.style == enums.ButtonStyle.DANGER
    assert announce.build_markup(None, None) is None


async def test_poster_hook_falls_back_to_cover(monkeypatch):
    import Tools.poster as poster

    async def broken(info): raise RuntimeError("designer crashed")
    monkeypatch.setattr(poster, "_custom_make_poster", broken)
    assert await poster.make_poster({"poster": "http://cover"}) == "http://cover"

    async def good(info): return "/tmp/poster.png"
    monkeypatch.setattr(poster, "_custom_make_poster", good)
    assert await poster.make_poster({"poster": "http://cover"}) == "/tmp/poster.png"


# ------------------------------------------------------------------ service ---
class FakeChat:
    def __init__(self, cid, title="My Channel", ctype="CHANNEL", status="ADMINISTRATOR", post=True, invite=True, no_member=False):
        self.cid, self.title, self.ctype, self.status, self.post, self.invite, self.no_member = cid, title, ctype, status, post, invite, no_member
        self.links = []

    async def get_chat(self, cid):
        return NS(id=cid, title=self.title, type=NS(name=self.ctype))

    async def get_chat_member(self, cid, who):
        if self.no_member:
            raise RuntimeError("USER_NOT_PARTICIPANT")
        return NS(status=NS(name=self.status), privileges=NS(can_post_messages=self.post, can_invite_users=self.invite))

    async def create_chat_invite_link(self, cid, name=None, creates_join_request=False):
        self.links.append(creates_join_request)
        return NS(invite_link="https://t.me/+JOIN")


@pytest.mark.parametrize("kw,fragment", [
    (dict(no_member=True), "not a member"),
    (dict(status="MEMBER"), "not an admin"),
    (dict(post=False), "Post messages"),
    (dict(ctype="PRIVATE"), "not a channel"),
])
async def test_channel_validation_messages(kw, fragment):
    with pytest.raises(MapError) as err:
        await chservice.check_channel(CH, FakeChat(CH, **kw))
    assert fragment in str(err.value)


async def test_create_mapping_baseline_and_join_request_link(monkeypatch):
    use_web(monkeypatch, FakeWeb())
    chat = FakeChat(CH)
    res = await chservice.create_mapping("Solo Leveling", "https://www.mgeko.cc/manga/solo/", CH, 222, bot=chat)
    doc = res["doc"]
    assert doc["posted"] == ["1", "2", "3"] and doc["last_chapter"] == "3" and res["latest"] == "3"
    assert doc["invite_link"] == "https://t.me/+JOIN" and chat.links == [True]      # join-REQUEST link
    assert doc["poster"] == "http://cover/x.jpg" and doc["channel_title"] == "My Channel"
    with pytest.raises(MapError):                                                   # duplicate
        await chservice.create_mapping("Solo Leveling", "https://www.mgeko.cc/manga/solo/", CH, 222, bot=chat)


async def test_create_mapping_rejects_unsupported_site_and_bad_page(monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=()))
    with pytest.raises(MapError) as err:
        await chservice.create_mapping("X", "https://unknown.example/a", CH, 222, bot=FakeChat(CH))
    assert "Unsupported site" in str(err.value)
    with pytest.raises(MapError) as err:
        await chservice.create_mapping("X", "https://www.mgeko.cc/manga/x/", CH, 222, bot=FakeChat(CH))
    assert "no chapters" in str(err.value)


async def test_create_mapping_last_n_queues_newest(clean_state, monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=("Chapter 5", "Chapter 4", "Chapter 3", "Chapter 2", "Chapter 1")))
    res = await chservice.create_mapping("Solo", "https://www.mgeko.cc/manga/solo/", CH, 222, last_n=2, bot=FakeChat(CH))
    assert res["queued"] == 2 and res["doc"]["posted"] == ["1", "2", "3"]


async def test_remove_pause_resume_and_export_import_roundtrip(clean_state, monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=("Chapter 4", "Chapter 3")))
    doc = await add_doc(posted=("3",))
    await chpoller.check_map(doc)
    assert clean_state.queue.qsize() == 1
    await chservice.set_status(doc["_id"], "paused")
    assert clean_state.queue.qsize() == 0 and (await chmap.get_map(doc["_id"]))["status"] == "paused"
    await chservice.set_status(doc["_id"], "active")
    got = await chmap.get_map(doc["_id"])
    assert got["status"] == "active" and got["next_check"] == 0

    text = chservice.export_lines([got])
    entries, bad = chmap.parse_import_lines(text)
    assert not bad and entries == [("Solo Leveling", "https://www.mgeko.cc/manga/solo/", CH)]

    assert await chservice.remove_mapping(doc["_id"]) and await chmap.get_map(doc["_id"]) is None


async def test_backfill_range(clean_state, monkeypatch):
    use_web(monkeypatch, FakeWeb(titles=("Chapter 5", "Chapter 4", "Chapter 3", "Chapter 2", "Chapter 1")))
    doc = await add_doc(posted=("1", "2", "3", "4", "5"))
    res = await chservice.backfill(doc, 2, 4)
    assert res == {"found": 3, "queued": 3}
    with pytest.raises(MapError):
        await chservice.backfill(doc, 100, 200)


async def test_import_many_continues_after_errors(monkeypatch):
    use_web(monkeypatch, FakeWeb())
    chat = FakeChat(CH)
    entries = [("A", "https://www.mgeko.cc/manga/a/", CH), ("B", "https://nope.example/b", CH),
               ("C", "https://www.mgeko.cc/manga/c/", CH)]
    out = await chservice.import_many(entries, 222, bot=chat)
    assert sorted(d["title"] for d in out["ok"]) == ["A", "C"] and len(out["failed"]) == 1


# ------------------------------------------------- poster design + announce ---
async def test_poster_design_renders_with_real_cover_and_long_title(server):
    from PIL import Image
    import Tools.poster as poster
    buf = await poster.make_poster({
        "title": "The Beginning After The End: Remake Of The Legendary King Who Returned",
        "chapter": "201.5", "site": "mgeko.cc", "poster": f"{server}/ok/1", "pages": 40,
    })
    img = Image.open(buf)
    assert img.size == (1920, 1080) and buf.name.endswith(".jpg")
    assert 20_000 < len(buf.getvalue()) < 9_000_000           # Telegram photo limit is 10 MB


async def test_poster_still_renders_when_cover_is_unreachable():
    import Tools.poster as poster
    buf = await poster.make_poster({"title": "X", "chapter": "1", "site": "s", "poster": "http://127.0.0.1:1/none.jpg"})
    assert buf.getvalue()[:2] == b"\xff\xd8"                  # a JPEG (placeholder cover), never an exception


async def test_announce_sends_poster_caption_and_always_has_join_button(monkeypatch):
    sent = []

    class B:
        async def send_photo(self, chat, photo, caption=None, reply_markup=None):
            sent.append(("photo", chat, photo, caption, reply_markup))
    monkeypatch.setattr(announce, "Bot", B())
    monkeypatch.setattr(announce.Vars, "UPDATE_CHANNEL", -100777)
    made = []

    async def fake_poster(info):
        made.append(info); return "poster-bytes"
    monkeypatch.setattr(announce, "make_poster", fake_poster)
    links = []

    async def fake_link(channel_id, bot=None):
        links.append(channel_id); return "https://t.me/+NEW"
    monkeypatch.setattr(chservice, "make_invite_link", fake_link)

    doc = await add_doc(invite_link=None)                      # mapping without a stored link
    ok, _why = await announce.announce_chapter(doc, "58", 40, NS(link="https://t.me/c/1/9"))
    assert ok and links == [CH]
    kind, chat, photo, caption, markup = sent[0]
    assert chat == -100777 and photo == "poster-bytes"
    assert "chapter" in caption and "added, read now" in caption and "Solo Leveling" in caption and "58" in caption
    urls = [b.url for row in markup.inline_keyboard for b in row]
    assert urls == ["https://t.me/+NEW"]   # single red join-request button
    assert (await chmap.get_map(doc["_id"]))["invite_link"] == "https://t.me/+NEW"      # remembered for next time
    assert made[0]["title"] == "Solo Leveling"


async def test_announce_falls_back_to_text_and_is_silent_when_disabled(monkeypatch):
    texts = []

    class B:
        async def send_photo(self, *a, **k): raise RuntimeError("PHOTO_INVALID_DIMENSIONS")
        async def send_message(self, chat, text, reply_markup=None, **k): texts.append((chat, text, reply_markup))
    monkeypatch.setattr(announce, "Bot", B())
    monkeypatch.setattr(announce.Vars, "UPDATE_CHANNEL", -100777)
    doc = await add_doc()
    assert (await announce.announce_chapter(doc, "5", 10))[0]
    assert texts and texts[0][2] is not None and "added, read now" in texts[0][1]
    monkeypatch.setattr(announce.Vars, "ANNOUNCE", False)
    assert not (await announce.announce_chapter(doc, "6", 10))[0]

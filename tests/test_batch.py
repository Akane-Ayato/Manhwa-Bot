"""Batch / latest mapping modes, settle check, disk guard, removal clean-up."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from Tools import chmap, chpoller, chservice
from Tools.chmap import MapError
from config import Vars
from tests.test_chmap import CH, FakeChat, FakeWeb, add_doc, clean_state, use_web  # noqa: F401

URL = "https://www.mgeko.cc/manga/solo/"
FIVE = ("Chapter 5", "Chapter 4", "Chapter 3", "Chapter 2", "Chapter 1")


@pytest.fixture
def announces(monkeypatch):
    got = []

    async def fake(doc, label, pages, msg=None, many=False):
        got.append((label, many))
        return True, ""
    monkeypatch.setattr(chpoller, "announce_chapter", fake)
    return got


async def finish_next(q):
    """Pretend the worker uploaded the next queued chapter."""
    card, _ = await q.get(1)
    await card.on_success(card, [])
    await q.task_done(card)
    await asyncio.sleep(0)          # let the scheduled refill run
    await asyncio.sleep(0)
    return card.chapter_key


async def test_batch_mode_posts_everything_then_ONE_update_post(clean_state, monkeypatch, announces):
    use_web(monkeypatch, FakeWeb(titles=FIVE))
    res = await chservice.create_mapping("Solo", URL, CH, 222, bot=FakeChat(CH), mode="batch")
    doc = res["doc"]
    assert doc["state"] == "batch" and doc["posted"] == [] and len(doc["batch_items"]) == 5
    assert res["queued"] == Vars.BATCH_DEPTH                      # lazy: only 2 at a time, not 5
    order = []
    for _ in range(5):
        order.append(await finish_next(clean_state.queue))
    assert order == ["1", "2", "3", "4", "5"]                     # channel order == chapter order
    assert announces == [("1-5", True)]                           # exactly ONE post, after the last chapter
    got = await chmap.get_map(doc["_id"])
    assert got["state"] == "live" and got["batch_items"] == [] and got["posted"] == ["1", "2", "3", "4", "5"]


async def test_latest_mode_posts_only_future_chapters_one_post_each(clean_state, monkeypatch, announces):
    web = FakeWeb(titles=("Chapter 3", "Chapter 2", "Chapter 1"))
    use_web(monkeypatch, web)
    res = await chservice.create_mapping("Solo", URL, CH, 222, bot=FakeChat(CH), mode="latest")
    assert res["queued"] == 0 and res["doc"]["state"] == "live"
    web.titles = ["Chapter 5", "Chapter 4"] + web.titles
    doc = await chmap.get_map(res["doc"]["_id"])
    assert (await chpoller.check_map(doc))["queued"] == 2
    await finish_next(clean_state.queue)
    await finish_next(clean_state.queue)
    assert announces == [("4", False), ("5", False)]


async def test_batch_resumes_after_restart_from_posted_list(clean_state, monkeypatch, announces):
    use_web(monkeypatch, FakeWeb(titles=FIVE))
    res = await chservice.create_mapping("Solo", URL, CH, 222, bot=FakeChat(CH), mode="batch")
    await finish_next(clean_state.queue)                          # chapter 1 done, 2 and 3 now queued
    for tid in list(clean_state.queue.storage_data):              # "restart": the in-memory queue is lost
        clean_state.queue.storage_data.pop(tid)
    out = await chpoller.refill_batch(res["doc"]["_id"])
    assert out["queued"] >= 1
    card, _ = await clean_state.queue.get(1)
    assert card.chapter_key == "2"                                # continues where it stopped, no repeat of 1


async def test_failed_batch_chapter_blocks_later_ones(clean_state, monkeypatch, announces):
    use_web(monkeypatch, FakeWeb(titles=FIVE))
    res = await chservice.create_mapping("Solo", URL, CH, 222, bot=FakeChat(CH), mode="batch")
    mid = res["doc"]["_id"]
    for _ in range(Vars.RETRY_LIMIT):
        await chpoller.add_failure(mid, "1", "Chapter 1", "boom")
    for tid in list(clean_state.queue.storage_data):
        clean_state.queue.storage_data.pop(tid)
    out = await chpoller.refill_batch(mid)
    assert out["queued"] == 0 and "failed" in out["blocked"]
    assert announces == []


async def test_remove_mapping_purges_queue_failures_and_late_success_is_silent(clean_state, monkeypatch, announces):
    use_web(monkeypatch, FakeWeb(titles=FIVE))
    res = await chservice.create_mapping("Solo", URL, CH, 222, bot=FakeChat(CH), mode="batch")
    mid = res["doc"]["_id"]
    running, _ = await clean_state.queue.get(1)                   # one chapter is "uploading" right now
    await chpoller.add_failure(mid, "9", "x", "e")
    assert await chservice.remove_mapping(mid)
    assert not clean_state.queue.storage_data                     # waiting chapter dropped
    assert await chpoller.list_failures(mid) == [] and await chmap.get_map(mid) is None
    await running.on_success(running, [])                         # late success of the running one
    assert announces == []
    assert await chmap.get_map(mid) is None                       # nothing resurrected


async def test_disk_guard_holds_auto_uploads(clean_state, monkeypatch, announces):
    use_web(monkeypatch, FakeWeb(titles=FIVE))
    monkeypatch.setattr(chpoller, "disk_ok", lambda: False)
    res = await chservice.create_mapping("Solo", URL, CH, 222, bot=FakeChat(CH), mode="batch")
    assert res["queued"] == 0 and not clean_state.queue.storage_data
    monkeypatch.setattr(chpoller, "disk_ok", lambda: True)
    assert (await chpoller.refill_batch(res["doc"]["_id"]))["queued"] == Vars.BATCH_DEPTH


async def test_auto_upload_off_pauses_posting(clean_state, monkeypatch, announces):
    from Tools.db import database
    web = FakeWeb(titles=("Chapter 4", "Chapter 3"))
    use_web(monkeypatch, web)
    doc = await add_doc(posted=("3",))
    await database.users.update_one({"_id": "222"}, {"$set": {"setting.auto_upload": False}}, upsert=True)
    out = await chpoller.check_map(doc)
    assert out["queued"] == 0 and "off" in out["skipped"]


async def test_settle_check_waits_until_chapter_page_list_is_stable(clean_state, monkeypatch):
    web = FakeWeb(titles=("Chapter 4", "Chapter 3"))
    use_web(monkeypatch, web)
    monkeypatch.setattr(Vars, "SETTLE_SECONDS", 0.01)
    calls = {"n": 0}

    async def growing(url, data=None):                            # site still adding pages
        calls["n"] += 1
        return [f"http://x/{i}" for i in range(calls["n"])]
    web.get_pictures = growing
    doc = await add_doc(posted=("3",))
    assert (await chpoller.check_map(doc))["queued"] == 0
    assert not clean_state.queue.storage_data

    async def stable(url, data=None):
        return [f"http://x/{i}" for i in range(5)]
    web.get_pictures = stable
    assert (await chpoller.check_map(doc))["queued"] == 1

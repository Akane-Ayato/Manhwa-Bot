import asyncio
import importlib
import time

import pytest

from Tools.base import AQueue, TaskCard, TTLCache, episode_sort_key, get_file_name, igrone_error
from Tools.cworker import safe_filename
from Tools.db import database, get_episode_number, asura_slug


# ---------------- config ----------------
def test_config_parsing(monkeypatch):
    import config
    monkeypatch.setenv("ADMINS", "1,2 3")
    monkeypatch.setenv("IS_PRIVATE", "False")
    monkeypatch.setenv("SHORTENER", "true")
    monkeypatch.setenv("CONSTANT_DUMP_CHANNEL", "-1001234")
    monkeypatch.setenv("OWNER", "9")
    importlib.reload(config)
    V = config.Vars
    assert V.ADMINS == [1, 2, 3, 9]
    assert V.IS_PRIVATE is False          # "False" used to be truthy
    assert V.SHORTENER is True
    assert V.CONSTANT_DUMP_CHANNEL == -1001234


def test_config_no_default_admins(monkeypatch):
    import config
    monkeypatch.delenv("ADMINS", raising=False)
    monkeypatch.delenv("OWNER", raising=False)
    importlib.reload(config)
    assert config.Vars.ADMINS == []       # original default granted admin to 3 strangers


def test_validate_config(monkeypatch):
    import config
    for k in ("API_ID", "API_HASH", "BOT_TOKEN", "DB_URL"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(config)
    assert len(config.validate_config()) == 4


# ---------------- parsing helpers ----------------
@pytest.mark.parametrize("title,expected", [
    ("Chapter 12", "12"), ("Chapter 10.5", "10.5"), ("Vol.3 Chapter 7", "7"),
    ("Ch.45", "45"), ("Episode 8", "8"), ("Solo Leveling Chapter 100.pdf", "100"),
    ("", None), (None, None), ("no digits here", None),
])
def test_episode_number(title, expected):
    assert get_episode_number(title) == expected


@pytest.mark.parametrize("a,b", [("2", "10"), ("2", "10.5"), ("9.5", "10"), ("3", "10 - 12")])
def test_sort_key_numeric(a, b):
    assert episode_sort_key(a) < episode_sort_key(b)


def test_sort_key_unknown_last():
    assert episode_sort_key("None") > episode_sort_key("999")
    assert episode_sort_key(None) > episode_sort_key("999")


def test_safe_filename():
    assert "/" not in safe_filename("a/b\\c:d*e?f")
    assert safe_filename("../../etc/passwd") == "etc passwd" or "/" not in safe_filename("../../etc/passwd")
    assert safe_filename("???") == "chapter"
    assert len(safe_filename("x" * 500)) <= 120


def test_get_file_name_zfill_and_bad_regex():
    data = [{"title": "Chapter 5", "manga_title": "My Manga!"}]
    assert get_file_name(data, {"regex": "3"})[2] == "005"
    assert get_file_name(data, {"regex": "junk"})[2] == "5"   # used to raise ValueError
    merged = [{"title": "Chapter 5", "manga_title": "M"}, {"title": "Chapter 7", "manga_title": "M"}]
    assert get_file_name(merged, {})[2] == "5 - 7"


def test_asura_slug():
    assert asura_slug("https://asurascans.com/comics/solo-leveling-1a2b3c") == "solo-leveling"


# ---------------- TTLCache ----------------
def test_ttlcache_update_no_deadlock():
    c = TTLCache(default_timeout=5, cleanup_interval=0)
    c.update({"a": 1, "b": 2})            # deadlocked with a non-reentrant Lock
    assert c.get("a") == 1 and len(c) == 2


def test_ttlcache_expiry_and_cap():
    c = TTLCache(default_timeout=5, cleanup_interval=0, max_entries=3)
    for i in range(10):
        c.set(i, i, timeout=100 + i)
    assert len(c) == 3
    c.set("x", 1, timeout=-1)
    assert "x" not in c


async def test_igrone_error_passes_propagation():
    import pyrogram

    async def boom():
        raise pyrogram.ContinuePropagation

    async def bad():
        raise RuntimeError("x")

    with pytest.raises(pyrogram.ContinuePropagation):
        await igrone_error(boom)()
    assert await igrone_error(bad)() is None


# ---------------- queue ----------------
def card(user, ep, prio=0, tid=None):
    c = TaskCard(webs=None, sts=None, picturesList=["u"], user_id=user, chat_id=user,
                 priority=prio, data_list=[{"title": f"Chapter {ep}", "manga_title": "M", "url": f"u{ep}"}],
                 settings={"x": 1})
    return c


async def test_queue_one_task_per_user_and_order():
    q = AQueue()
    for ep in (3, 1, 2):
        await q.put(card(1, ep))
    t1, _ = await q.get(0)
    assert t1.episode_number == "1"
    assert q.get_available_tasks() is None          # user 1 busy
    assert await q.task_done(t1) is True
    t2, _ = await q.get(0)
    assert t2.episode_number == "2"


async def test_queue_fifo_between_users_and_premium_priority():
    q = AQueue()
    await q.put(card(1, 50))
    await q.put(card(2, 1))                          # lower chapter, but arrived later
    first, _ = await q.get(0)
    assert first.user_id == 1                        # FIFO across users (was: global chapter sort)
    q2 = AQueue()
    await q2.put(card(1, 5, prio=0))
    await q2.put(card(2, 9, prio=1))
    prem, _ = await q2.get(0)
    assert prem.user_id == 2                         # premium first (priority was ignored)


async def test_queue_delete_task_and_delete_tasks():
    q = AQueue()
    tid = await q.put(card(1, 1))
    await q.put(card(1, 2))
    await q.put(card(2, 1))
    assert await q.delete_task(tid) is True
    assert await q.delete_task("nope") is False
    assert await q.delete_tasks(1) == 1
    assert q.get_count(1) == 0 and q.get_count(2) == 1 and q.get_count() == 1


async def test_queue_delete_ongoing_does_not_crash():
    q = AQueue()
    tid = await q.put(card(1, 1))
    t, _ = await q.get(0)
    assert await q.delete_task(tid) is False          # already running (used to raise KeyError path)
    assert await q.task_done(t)


async def test_queue_get_blocks_until_put():
    q = AQueue()
    getter = asyncio.create_task(q.get(0))
    await asyncio.sleep(0.1)
    assert not getter.done()
    await q.put(card(7, 1))
    t, _ = await asyncio.wait_for(getter, 3)
    assert t.user_id == 7


async def test_queue_update_tasks_cannot_be_cancelled():
    q = AQueue()
    tid = await q.put(card(1, 1), True)
    await q.delete_task(tid)
    assert q.qsize() == 1


def test_taskcard_requires_chapters():
    with pytest.raises(ValueError):
        TaskCard(None, None, [], 1, 1, 0, data_list=[])


# ---------------- database ----------------
async def test_settings_roundtrip_and_defaults():
    assert await database.get_settings(5) == {}
    await database.ensure_user(5)
    await database.set_value(5, "caption", "hi")
    assert (await database.get_settings(5))["caption"] == "hi"
    await database.delete_value(5, "caption")
    assert "caption" not in await database.get_settings(5)


async def test_subscriptions_cycle():
    d = {"url": "https://x.com/m/1", "title": "T", "lastest_chapter": "Chapter 1"}
    assert await database.add_sub(1, dict(d), "mf") is True
    assert await database.add_sub(1, dict(d), "mf") is False       # duplicate
    assert await database.check_sub(1, d["url"], "mf") is True
    assert await database.check_sub(1, d["url"]) is True            # url only ($elemMatch bug)
    assert (await database.get_subs(1, d["url"], "mf"))["title"] == "T"
    assert await database.save_latest_chapter({"url": d["url"], "title": "T", "lastest_chapter": "Chapter 2"}, 1, "mf")
    assert (await database.get_subs(1, d["url"], "mf"))["lastest_chapter"] == "Chapter 2"
    assert await database.delete_sub(1, d["url"], "mf") is True
    assert await database.get_subs(1) is None or await database.get_subs(1) == []


async def test_asura_subscription_survives_url_hash_change():
    old = {"url": "https://asurascans.com/comics/solo-leveling-aaa111", "title": "SL", "lastest_chapter": "Chapter 1"}
    assert await database.add_sub(1, dict(old), "as")
    new_url = "https://asurascans.com/comics/solo-leveling-bbb222"
    assert await database.add_sub(1, {"url": new_url, "title": "SL"}, "as") is False   # same series
    assert (await database.get_subs(1, new_url, "as"))["title"] == "SL"                # slug lookup (was broken)
    assert await database.check_sub(1, new_url, "as")
    assert await database.save_latest_chapter({"url": new_url, "title": "SL", "lastest_chapter": "Chapter 9"}, 1, "as")
    assert (await database.get_subs(1, new_url, "as"))["lastest_chapter"] == "Chapter 9"
    assert await database.delete_sub(1, new_url, "as")
    assert not await database.check_sub(1, new_url, "as")


async def test_channels_and_dump_lookup():
    await database.ensure_user(1)
    await database.add_channel(1, "target_channels", -100)
    await database.add_channel(1, "target_channels", -100)
    assert await database.get_target_channel(1) == [-100]
    assert await database.check_dump(-100) == "1"
    await database.remove_channel(1, "target_channels", -100)
    assert await database.get_target_channel(1) == []


async def test_premium_and_tokens():
    assert await database.add_premium(5, "2 weeks")
    p = await database.premium_user(5)
    assert p["days"] == 14
    ids = [u async for u, _ in database.get_all_premium()]
    assert ids == ["5"]
    assert await database.remove_premium(5)
    assert await database.premium_user(5) is None
    await database.save_token_data(1, {"token": "t", "expires_at": time.time() - 5})
    await database.save_token_data(2, {"token": "t", "expires_at": time.time() + 500})
    assert await database.purge_expired_tokens() == 1
    assert await database.get_token_data(2)
    assert await database.set_token_field(2, verify="True")
    assert (await database.get_token_data(2))["verify"] == "True"

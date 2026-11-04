import asyncio
import os
from types import SimpleNamespace as NS

import pytest

import Tools.cworker as cw
from Tools.base import AQueue, TaskCard
from tests.test_pipeline import Handler, server, fast_retries  # noqa: F401  (fixtures)


class FakeSts:
    def __init__(self, fail=False): self.fail, self.edits, self.deleted = fail, [], False
    async def edit(self, t, **kw):
        if self.fail: raise RuntimeError("MESSAGE_ID_INVALID")
        self.edits.append(t); return self
    edit_text = edit
    async def delete(self): self.deleted = True


class FakeBot:
    def __init__(self): self.groups, self.copies, self.sizes = [], [], []
    async def send_media_group(self, chat_id, media):
        for m in media: self.sizes.append((os.path.basename(m.media), os.path.getsize(m.media)))
        msgs = [NS(chat=NS(id=chat_id), id=100 + i, document=NS(file_name=os.path.basename(m.media))) for i, m in enumerate(media)]
        self.groups.append(msgs); return msgs
    async def send_document(self, chat_id, path, caption=None, thumb=None, progress=None):
        self.sizes.append((os.path.basename(path), os.path.getsize(path)))
        if progress: progress(os.path.getsize(path), os.path.getsize(path))  # exercises the upload progress callback
        msg = NS(chat=NS(id=chat_id), id=100, document=NS(file_name=os.path.basename(path)))
        self.groups.append([msg]); return msg
    async def copy_media_group(self, to, frm, mid, captions=None): self.copies.append((to, captions)); return []
    async def get_users(self, uid): return NS(mention=lambda: "user")
    async def send_message(self, *a, **k): return NS(copy=lambda *a, **k: _n())
    async def download_media(self, *a, **k): return None


async def _n(): return None


class FakeWebs:
    sf, url, cs = "xx", "http://localhost", False


@pytest.fixture
def env(monkeypatch, tmp_path, server):
    monkeypatch.chdir(tmp_path)
    bot = FakeBot()
    monkeypatch.setattr(cw, "Bot", bot)
    monkeypatch.setattr(cw.Vars, "CONSTANT_DUMP_CHANNEL", -555)
    monkeypatch.setattr(cw.Vars, "LOG_CHANNEL", -777)
    uploaded = []
    class U:
        async def upload_to_targets_channels(self, *a, **k): uploaded.append(k)
    monkeypatch.setattr(cw, "Uploader", U)
    q = AQueue(); monkeypatch.setattr(cw, "queue", q)
    return bot, uploaded, q, server


def make_card(server, settings, sts=None, n=3):
    return TaskCard(FakeWebs(), sts, [f"{server}/ok/{i}" for i in range(1, n + 1)], 10, 10, 0,
                    data_list=[{"title": "Chapter 7: The/End?", "manga_title": "Solo: Leveling/2", "url": "u", "poster": ""}],
                    settings=settings, tasks_id="t1")


async def test_full_chapter_pdf_and_cbz(env):
    bot, uploaded, q, server = env
    sts = FakeSts()
    card = make_card(server, {"type": ["PDF", "CBZ"], "dump": -888, "password": None, "compress": "50"}, sts)
    await cw.send_manga_chapter(card)

    names = [n for n, _ in bot.sizes]
    assert len(names) == 2 and names[0].endswith(".pdf") and names[1].endswith(".cbz")
    assert all("/" not in n and ":" not in n and "?" not in n for n in names)   # hostile title made safe
    assert all(size > 0 for _, size in bot.sizes)
    assert uploaded and uploaded[0]["original_ep_num"] == "7"
    assert {c[0] for c in bot.copies} == {-555, -888, -777}                    # constant dump, user dump, log
    assert sts.deleted
    assert not os.path.exists("Process/t1")                                    # temp files cleaned


async def test_download_failure_reports_error_and_cleans(env):
    bot, uploaded, q, server = env
    sts = FakeSts()
    card = make_card(server, {"type": ["PDF"]}, sts)
    card.picturesList = [f"{server}/missing"]
    await cw.send_manga_chapter(card)
    assert not bot.groups and any("Error at Downloading" in e for e in sts.edits)
    assert not os.path.exists("Process/t1")


async def test_target_channel_failure_does_not_lose_dump_or_report_failure(env, monkeypatch):
    bot, uploaded, q, server = env
    class Boom:
        async def upload_to_targets_channels(self, *a, **k): raise RuntimeError("channel exploded")
    monkeypatch.setattr(cw, "Uploader", Boom)
    sts = FakeSts()
    await cw.send_manga_chapter(make_card(server, {"type": ["PDF"], "dump": -888}, sts))
    assert {c[0] for c in bot.copies} == {-555, -888, -777}
    assert sts.deleted and not any("exploded" in e for e in sts.edits)


async def test_no_file_type_selected_gives_error(env):
    bot, uploaded, q, server = env
    sts = FakeSts()
    await cw.send_manga_chapter(make_card(server, {"type": ["nonsense"]}, sts))
    assert not bot.groups and any("No valid file type" in e for e in sts.edits)


async def test_worker_survives_deleted_status_message_and_releases_user(env, monkeypatch):
    bot, uploaded, q, server = env
    card = make_card(server, {"type": ["PDF"]}, FakeSts(fail=True))
    await q.put(card)
    w = asyncio.create_task(cw.worker(1))
    for _ in range(100):
        await asyncio.sleep(0.1)
        if bot.groups and not q.ongoing_tasks:
            break
    assert bot.groups, "chapter was not delivered"
    assert q.ongoing_tasks == {}                      # user slot released
    assert not w.done()                               # worker still alive
    w.cancel()

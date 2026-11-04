import asyncio
import pytest
import Tools.cworker as cw
from Tools.base import AQueue, TaskCard
from tests.test_chmap import FakeWeb


async def test_clean_cancels_running_and_pending_but_not_other_users_or_auto(monkeypatch):
    q = AQueue()
    monkeypatch.setattr(cw, "queue", q)
    started, finished = asyncio.Event(), []

    async def slow(card):
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            finished.append("cleanup ran")                      # the real function's `finally` = disk cleanup
    monkeypatch.setattr(cw, "send_manga_chapter", slow)

    def mk(uid, kind="user"):
        return TaskCard(data_list=[{"title": "t"}], picturesList=["p"], webs=FakeWeb(), sts=None,
                        user_id=uid, chat_id=uid, priority=0, update_mode=True, settings={"x": 1}, kind=kind)
    mine, other, auto = mk(5), mk(6), mk(-100123, "auto")
    for c in (mine, other, auto):
        await q.put(c, True)
    w = asyncio.create_task(cw.worker(1))
    await asyncio.wait_for(started.wait(), 5)
    running_owner = [t for t in q.ongoing_tasks.values()][0].user_id
    pend, run = await q.cancel_user(running_owner)
    await asyncio.sleep(0.2)
    assert run == 1 and finished == ["cleanup ran"]
    assert w.done() is False                                    # the worker survived the cancellation
    w.cancel()

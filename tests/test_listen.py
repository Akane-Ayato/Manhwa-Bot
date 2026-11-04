import asyncio
from types import SimpleNamespace as NS

import pytest
from pyrogram import filters

import Tools.listen as lt


def client():
    # real pyrogram filters run sync predicates through client.loop / client.executor
    return NS(loop=asyncio.get_running_loop(), executor=None)


class Msg:
    def __init__(self, uid, text="hi"):
        self.from_user, self.text = NS(id=uid), text


async def test_listen_receives_next_matching_message_and_consumes_it():
    task = asyncio.create_task(lt.listen(None, user_id=5, timeout=2))
    await asyncio.sleep(0.01)
    assert not await lt.feed(None, Msg(6))                  # other user: untouched
    assert await lt.feed(None, Msg(5, "caption text"))
    got = await task
    assert got.text == "caption text" and lt._pending == {}
    assert not await lt.feed(None, Msg(5))                  # nobody listening any more


async def test_listen_filters_and_timeout():
    async def is_yes(_, __, m):
        return m.text == "yes"
    flt = filters.create(is_yes) & filters.create(lambda _, __, m: True)
    task = asyncio.create_task(lt.listen(None, user_id=5, timeout=0.3, filters=flt))
    await asyncio.sleep(0.01)
    assert not await lt.feed(client(), Msg(5, "no"))        # filter rejects -> goes on to normal handlers
    assert await lt.feed(client(), Msg(5, "yes"))
    assert (await task).text == "yes"
    with pytest.raises(lt.ListenerTimeout):
        await lt.listen(None, user_id=5, timeout=0.05)
    assert lt._pending == {}                                # cleaned up after timeout


async def test_install_adds_listen_when_missing_and_settings_imports():
    import TG.settings  # noqa: F401   (used to crash on kurigram: no pyromod)
    from pyrogram import Client
    assert hasattr(Client, "listen")                        # native (pyrofork) or installed (kurigram)

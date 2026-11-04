"""`client.listen(user_id=..., timeout=..., filters=...)` for forks that do not ship pyromod.

pyrofork has `Client.listen` built in; kurigram does not.  The settings panel asks the user
for a value ("send the caption") and waits for the next matching message with `listen()`,
so this module provides the same API:

    msg = await client.listen(user_id=123, timeout=60, filters=filters.text)   # raises ListenerTimeout

It is only installed when `Client.listen` is missing.  The waiting message is consumed
(handlers of later groups do not see it), exactly like pyromod does.
"""
import asyncio
from typing import Dict, List, Optional, Tuple

from pyrogram import Client, filters as pyro_filters

try:  # pyrofork ships its own exception
    from pyrogram.errors.pyromod.listener_timeout import ListenerTimeout  # type: ignore
except Exception:
    class ListenerTimeout(Exception):
        """No matching message arrived before the timeout."""


NATIVE = hasattr(Client, "listen")          # True on pyrofork: nothing to install

_pending: Dict[int, List[Tuple[asyncio.Future, Optional[object]]]] = {}


async def listen(self, user_id: Optional[int] = None, chat_id: Optional[int] = None,
                 timeout: Optional[float] = None, filters=None):
    key = user_id if user_id is not None else chat_id
    if key is None:
        raise ValueError("listen() needs user_id or chat_id")
    future = asyncio.get_running_loop().create_future()
    entry = (future, filters)
    _pending.setdefault(int(key), []).append(entry)
    try:
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        raise ListenerTimeout(timeout)
    finally:
        entries = _pending.get(int(key), [])
        if entry in entries:
            entries.remove(entry)
        if not entries:
            _pending.pop(int(key), None)


async def feed(client, message) -> bool:
    """Give `message` to a waiting listener.  True if one took it."""
    user = getattr(message, "from_user", None)
    if not user:
        return False
    for future, flt in list(_pending.get(user.id, [])):
        if future.done():
            continue
        try:
            matched = True if flt is None else await flt(client, message)
        except Exception:
            matched = False
        if matched:
            future.set_result(message)
            return True
    return False


def install(bot) -> None:
    """Add `Client.listen` and the high-priority handler that feeds it (no-op on pyrofork)."""
    if NATIVE:
        return
    Client.listen = listen

    @bot.on_message(pyro_filters.private, group=-2)
    async def _listener_gate(client, message):
        if await feed(client, message):
            message.stop_propagation()

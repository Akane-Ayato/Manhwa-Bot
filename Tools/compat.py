"""Small helpers so the code runs on pyrofork AND kurigram (their Message APIs differ)."""


def forwarded_chat(message):
    """The chat a message was forwarded from (channel/group), else None.

    pyrofork: message.forward_from_chat   |   kurigram: message.forward_origin.chat / .sender_chat"""
    chat = getattr(message, "forward_from_chat", None)
    if chat:
        return chat
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None
    return getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)


# --------------------------------------------------------------------------
# kurigram: Message.reply_*() no longer takes `quote=` (it always replies to the message) and
# `disable_web_page_preview=` became `link_preview_options=`.  The bot uses both in many places, so
# instead of editing every call, accept the old keywords and translate them.  No-op on pyrofork.
# --------------------------------------------------------------------------
import functools
import inspect


def _adapt_reply(func):
    params = inspect.signature(func).parameters
    takes_quote = "quote" in params
    takes_preview = "disable_web_page_preview" in params

    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not takes_quote:
            kwargs.pop("quote", None)  # kurigram always replies to the message
        if not takes_preview and "disable_web_page_preview" in kwargs:
            disabled = kwargs.pop("disable_web_page_preview")
            if disabled and "link_preview_options" in params and "link_preview_options" not in kwargs:
                from pyrogram.types import LinkPreviewOptions
                kwargs["link_preview_options"] = LinkPreviewOptions(is_disabled=True)
        return await func(self, *args, **kwargs)

    wrapper._kw_adapted = True
    return wrapper


def install_kwargs_compat() -> int:
    """Patch Message.reply*/ Message.edit_text so old pyrofork keywords keep working.  Returns #methods patched."""
    from pyrogram.types import Message

    patched = 0
    for name in dir(Message):
        if not (name.startswith("reply") or name in ("edit_text", "edit")):
            continue
        func = getattr(Message, name, None)
        # pyrogram wraps its async methods in a sync/async bridge, so look through the wrapper
        if not callable(func) or not inspect.iscoroutinefunction(inspect.unwrap(func)) \
                or getattr(func, "_kw_adapted", False):
            continue
        params = inspect.signature(func).parameters
        needs = ("quote" not in params and name.startswith("reply")) or \
                ("disable_web_page_preview" not in params and "link_preview_options" in params)
        if needs:
            setattr(Message, name, _adapt_reply(func))
            patched += 1
    return patched

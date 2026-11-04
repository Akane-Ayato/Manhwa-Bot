from types import SimpleNamespace as NS

import pytest
from pyrogram.types import Message

import bot  # noqa: F401  (installs the keyword compat)
from Tools.compat import _adapt_reply, forwarded_chat, install_kwargs_compat


async def test_adapter_drops_quote_and_translates_preview_flag():
    pytest.importorskip("pyrogram.types").__dict__.get("LinkPreviewOptions") or pytest.skip("pyrofork has no LinkPreviewOptions")
    seen = {}

    async def reply_text(self, text, link_preview_options=None, reply_markup=None):
        seen.update(text=text, lpo=link_preview_options, markup=reply_markup)

    await _adapt_reply(reply_text)(object(), "hi", quote=True, disable_web_page_preview=True, reply_markup="M")
    assert seen["text"] == "hi" and seen["markup"] == "M" and seen["lpo"].is_disabled is True


async def test_adapter_leaves_libraries_that_know_the_keywords_alone():
    seen = {}

    async def reply_text(self, text, quote=None, disable_web_page_preview=None):
        seen.update(quote=quote, preview=disable_web_page_preview)

    await _adapt_reply(reply_text)(object(), "hi", quote=True, disable_web_page_preview=True)
    assert seen == {"quote": True, "preview": True}


async def test_real_message_reply_photo_accepts_quote_like_start_command():
    """The exact call that crashed /start on kurigram."""
    sent = {}

    class Client:
        async def send_photo(self, chat_id, photo, **kw):
            sent.update(chat=chat_id, photo=photo, **kw); return "ok"

    if "quote" in __import__("inspect").signature(Message.reply_photo).parameters:
        pytest.skip("this library still supports quote= natively")
    msg = Message(id=7, client=Client())
    msg.chat = NS(id=55)
    await msg.reply_photo("http://x/p.jpg", caption="cat", reply_markup=None, quote=True)
    assert sent["chat"] == 55 and sent["caption"] == "ᴄᴀᴛ"   # style layer ran too


def test_install_is_idempotent():
    install_kwargs_compat()
    assert install_kwargs_compat() == 0


def test_forwarded_chat_both_libraries():
    chat = NS(id=-100)
    assert forwarded_chat(NS(forward_from_chat=chat)) is chat                       # pyrofork
    assert forwarded_chat(NS(forward_origin=NS(chat=chat))) is chat                 # kurigram, channel
    assert forwarded_chat(NS(forward_origin=NS(sender_chat=chat))) is chat          # kurigram, chat
    assert forwarded_chat(NS(forward_origin=None)) is None and forwarded_chat(NS()) is None

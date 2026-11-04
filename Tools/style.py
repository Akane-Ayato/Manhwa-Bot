"""UI look: ꜱᴍᴀʟʟ ᴄᴀᴘꜱ text and plain symbols instead of emojis - applied to every bot message in one place.

`style_text()` converts only the visible words.  It leaves untouched: HTML tags, <code>/<pre>/`code`,
links, @mentions, /commands, {placeholders} and HTML entities.  Capital letters stay capital
(so "Hello" -> "Hᴇʟʟᴏ"); the function is idempotent.  `install()` patches the pyrogram send/edit methods so
no handler has to change.  File captions of uploaded chapters are NOT styled (they belong to the user).
"""
import functools
import inspect
import re

SMALL = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))
_TABLE = {ord(k): v for k, v in SMALL.items()}

SYMBOLS = {
    # emoji -> plain text symbols (none of these is rendered as an emoji by Telegram)
    "✅": "✓", "❌": "✗", "❗": "!", "⚠": "▲", "⛔": "⊘", "⚡": "ϟ", "⚪": "○", "⚫": "●", "🟢": "●", "🔴": "◉",
    "🟡": "◎", "🟠": "◎", "🔵": "◉", "⏳": "⧖", "⌛": "⧖", "⏸": "‖", "⏭": "»", "⏩": "»", "⏪": "«", "▶": "▸",
    "◀": "◂", "🔁": "⟳", "🔄": "⟳", "🗑": "✕", "🛠": "✦", "⚙": "✦", "🧩": "❖", "📖": "❖", "📙": "❖", "📚": "❖",
    "📢": "➥", "📋": "≡", "📌": "✦", "📊": "▤", "📐": "◈", "🌐": "◍", "👉": "➥", "👑": "♕", "👤": "♞",
    "🤖": "♚", "🔍": "⌕", "🔥": "✹", "🕒": "◔", "⏱": "◔", "🖥": "▣", "🚦": "◈", "🚧": "✕", "🧠": "◈",
    "🔌": "ϟ", "💾": "▣", "📂": "▤", "📤": "⇧", "📥": "⇩", "🎬": "▸", "🎮": "✦", "💘": "♡", "📟": "▣",
    "✏": "✎", "ℹ": "ⓘ", "➕": "✚", "☠": "✗", "🔔": "✦", "🔗": "⌘", "🔒": "▣", "⭐": "★", "✨": "✦",
    "✔": "✓", "✖": "✕", "‼": "!!", "❤": "♡", "♥": "♡", "☑": "✓", "✂": "✕", "⬆": "▲", "⬇": "▼", "➡": "➜",
    "⬅": "◂", "↩": "◂", "ℹ️": "ⓘ", "™": "", "©": "",
}
_SYM_RE = re.compile("|".join(map(re.escape, sorted(SYMBOLS, key=len, reverse=True))))
_LEFTOVER_EMOJI = re.compile("[\U0001F000-\U0001FAFF️‍]")

# spans that must stay byte-for-byte
_PROTECT = re.compile(
    r"<(code|pre)\b[^>]*>.*?</\1>"          # code blocks
    r"|```.*?```|`[^`\n]*`"                  # markdown code
    r"|<[^>]+>"                              # any tag
    r"|&#?\w+;"                              # entities
    r"|https?://\S+|t\.me/\S+"               # links
    r"|(?<![\w/])[/@][A-Za-z0-9_]+"          # /commands and @mentions
    r"|\{[^{}]*\}",                          # leftover placeholders
    re.S,
)


def _plain(segment: str) -> str:
    segment = _SYM_RE.sub(lambda m: SYMBOLS[m.group(0)], segment)
    segment = _LEFTOVER_EMOJI.sub("", segment)
    return segment.translate(_TABLE)


class Raw(str):
    """Text that must be sent exactly as written (user-authored captions / update texts)."""


def style_text(text):
    if not isinstance(text, str) or not text or isinstance(text, Raw):
        return text
    out, pos = [], 0
    for m in _PROTECT.finditer(text):
        out.append(_plain(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_plain(text[pos:]))
    return "".join(out)


# ----------------------------------------------------------------- patching ---
def _wrap(func, arg_names=("text", "caption")):
    """Return an async wrapper that styles the named kwargs (and the first positional text arg)."""
    params = list(inspect.signature(func).parameters)

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        args = list(args)
        for name in arg_names:
            if name in kwargs:
                kwargs[name] = style_text(kwargs[name])
            elif name in params:
                idx = params.index(name)
                if idx < len(args) and isinstance(args[idx], str):
                    args[idx] = style_text(args[idx])
        return await func(*args, **kwargs)

    wrapper._styled = True
    return wrapper


def install() -> int:
    """Patch pyrogram.  Safe to call twice.  Returns the number of patched callables."""
    from pyrogram import Client
    from pyrogram.types import (CallbackQuery, InlineKeyboardButton, InputMediaDocument, InputMediaPhoto,
                                InputMediaVideo, Message)

    count = 0
    targets = [
        (Message, ["reply_text", "reply", "reply_photo", "edit_text", "edit", "edit_caption"]),
        (CallbackQuery, ["answer", "edit_message_text", "edit_message_caption"]),
        (Client, ["send_message", "send_photo", "edit_message_text", "edit_message_caption"]),
    ]
    for cls, names in targets:
        for name in names:
            func = getattr(cls, name, None)
            if func is None or getattr(func, "_styled", False):
                continue
            if not inspect.iscoroutinefunction(inspect.unwrap(func)):
                continue
            setattr(cls, name, _wrap(func))
            count += 1

    # keyboard labels + media captions (settings panel uses edit_media(InputMediaPhoto(caption=...)))
    if not getattr(InlineKeyboardButton.__init__, "_styled", False):
        orig = InlineKeyboardButton.__init__

        @functools.wraps(orig)
        def button_init(self, text, *a, **k):
            return orig(self, style_text(text), *a, **k)
        button_init._styled = True
        InlineKeyboardButton.__init__ = button_init
        count += 1
    for media in (InputMediaPhoto, InputMediaVideo, InputMediaDocument):
        if getattr(media.__init__, "_styled", False):
            continue
        orig_m = media.__init__

        def make(orig_m=orig_m):
            @functools.wraps(orig_m)
            def media_init(self, *a, **k):
                if "caption" in k:
                    k["caption"] = style_text(k["caption"])
                return orig_m(self, *a, **k)
            media_init._styled = True
            return media_init
        media.__init__ = make()
        count += 1
    return count

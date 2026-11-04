"""Shortener-token gate ("verify through a short link to use the bot for N hours").

Rewritten from the original:
  * no blocking MongoClient / find_one() at import time (that crashed the whole
    bot at start-up whenever MongoDB was unreachable or DB_URL was empty);
  * tokens now live in one document per user in the `user_tokens` collection and
    are read/written through the shared async client in Tools.db;
  * `get_all_premuim` typo (AttributeError whenever SHORTENER was on) fixed;
  * `expired_token_` no longer mutates a dict while iterating it;
  * the shortener HTTP call has a timeout and runs in a thread (it used to
    block the event loop with no timeout);
  * an expired token now re-issues a link on a *bot* message (it used to try to
    edit the user's own message, which Telegram forbids).
"""
import asyncio
import functools
import random
import re
import string
import time

from curl_cffi import requests as http
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import Bot
from config import Vars
from Tools.db import database
from loguru import logger

TUTORIAL_URL = "https://t.me/How_to_Download_7x/32"
MIN_WAIT_SECONDS = 40  # a token verified faster than this is treated as a bypass


def generate_random_alphanumeric() -> str:
    """Generate a random 8-character alphanumeric token."""
    characters = string.ascii_letters + string.digits
    return "".join(random.choice(characters) for _ in range(8))


def generate_token() -> str:
    return generate_random_alphanumeric()


def _short_apis() -> list:
    return [a for a in re.split(r"[\s,]+", Vars.SHORTENER_API or "") if a]


def _get_short_sync(url: str) -> str:
    apis = _short_apis()
    if not apis:
        return url
    xurl = random.choice(apis).replace("{}", url)
    try:
        data = http.get(xurl, timeout=20).json()
        for key in ("shortenedUrl", "short_url", "shorturl", "result_url"):
            if isinstance(data, dict) and data.get(key):
                return data[key]
        logger.warning(f"Shortener response had no short url: {str(data)[:200]}")
    except Exception as e:
        logger.warning(f"Shortener request failed: {e}")
    return url


async def get_short(url: str) -> str:
    """Shorten `url`; falls back to the original link if the shortener fails."""
    return await asyncio.to_thread(_get_short_sync, url)


async def get_premuims() -> list:
    """IDs allowed to skip the token gate: active premium users + admins."""
    users_id_list = []
    async for user_id, data in database.get_all_premium():
        if data.get("expiration_timestamp", 0) > time.time():
            try:
                users_id_list.append(int(user_id))
            except (TypeError, ValueError):
                pass
    return users_id_list + list(Vars.ADMINS)


async def save_token(user_id, token: str, _id: int, _cid: int, short_token_link: str) -> None:
    now = time.time()
    await database.save_token_data(user_id, {
        "token": token,
        "expires_at": now + Vars.DURATION * 3600,
        "duration": now + MIN_WAIT_SECONDS,
        "msg_id": _id,
        "chat_id": _cid,
        "s_link": short_token_link,
        "verify": None,
    })


async def expired_token_() -> int:
    """Delete expired tokens; returns how many were removed."""
    return await database.purge_expired_tokens() or 0


def _keyboard(link: str, bypass: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("ɢᴇᴛ ᴛᴏᴋᴇɴ ", url=link)],
        [InlineKeyboardButton("ᴛᴜᴛᴏʀɪᴀʟ", url=TUTORIAL_URL)],
    ]
    if bypass:
        rows.append([
            InlineKeyboardButton("ᴘʀᴇᴍɪᴜᴍ", callback_data="premuim"),
            InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close"),
        ])
    else:
        rows.append([InlineKeyboardButton("ᴘʀᴇᴍɪᴜᴍ", callback_data="premuim")])
        rows.append([InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")])
    return InlineKeyboardMarkup(rows)


def check_token_(func):
    """Decorator for message handlers: require a verified shortener token (if SHORTENER is on)."""
    @functools.wraps(func)
    async def wrapper(client, message, *args, **kwargs):
        if not Vars.SHORTENER or not message.from_user:
            return await func(client, message, *args, **kwargs)

        user_id = message.from_user.id
        if user_id in await get_premuims():
            return await func(client, message, *args, **kwargs)

        data = await database.get_token_data(user_id)
        if data:
            if data.get("verify") == "True":
                if data.get("expires_at", 0) > time.time():
                    return await func(client, message, *args, **kwargs)
                sts = await message.reply("<i>ㅤProcessing.....</i>")
                return await get_token(sts, user_id)
            return await message.reply(
                f"ᴠᴇʀɪғʏ ʏᴏᴜʀ ᴛᴏᴋᴇɴ ғɪʀsᴛ {data.get('s_link', '')}"
            )

        sts = await message.reply("<i>ㅤProcessing.....</i>")
        return await get_token(sts, user_id)

    return wrapper


async def verify_token(message, user_id, token):
    """Handle `/start <token>`; `message` is a bot message we can edit."""
    user_id = str(user_id)
    data = await database.get_token_data(user_id)
    if not data or data.get("expires_at", 0) <= time.time():
        return await get_token(message, user_id)

    if data.get("verify") == "True":
        return await message.edit("ᴛᴏᴋᴇɴ ᴀʟʀᴇᴀᴅʏ ᴠᴇʀɪғɪᴇᴅ....")

    if data.get("token") != token:
        return await get_token(message, user_id)

    if data.get("duration", 0) < time.time():
        await database.set_token_field(user_id, verify="True")
        return await message.edit("ᴛᴏᴋᴇɴ ᴠᴇʀɪғɪᴇᴅ. ɴᴏᴡ, ʏᴏᴜ ᴄᴀɴ ᴜsᴇ ᴍᴇ sᴇɴᴅ /ᴜs")

    return await message.edit(Vars.BYPASS_TXT, reply_markup=_keyboard(data.get("s_link", ""), bypass=True))


async def get_token(message, user_id):
    """Issue a fresh token link and show it on `message` (a bot message)."""
    user_id = str(user_id)
    old = await database.get_token_data(user_id)
    if old and "msg_id" in old and "chat_id" in old:
        try:
            await Bot.delete_messages(int(old["chat_id"]), int(old["msg_id"]))
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except Exception:
            pass

    new_token = generate_token()
    token_link = f"https://telegram.me/{Bot.username}?start={new_token}"
    short_token_link = await get_short(token_link)
    await save_token(user_id, new_token, message.id, message.chat.id, short_token_link)

    text = (
        "<i>Invalid or expired token. Here is your new token link. "
        "Click the button below to use it.\n\n **Valid Till 1 days.**</i>"
    )
    try:
        await message.edit_text(text, reply_markup=_keyboard(short_token_link))
    except FloodWait as e:
        await asyncio.sleep(e.value + 2)
        await message.edit_text(text, reply_markup=_keyboard(short_token_link))

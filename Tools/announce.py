"""Update-channel post for mapped uploads: poster + text + buttons, built from the OWNER's settings.

Settings used (Settings panel):
  Update Channel  (update_c)  where the post goes (falls back to the UPDATE_CHANNEL env value)
  Update Text     (update_t)  text with {manga_title} {chapter_num} {channel_title} {channel_link} {read_link}
                              and "< label >link" link syntax; default: "<title> chapter <n> added, read now"
  Update Button   (update_b)  extra button rows ("Text - url | Text - url", one row per line)
  Update Sticker  (update_s)  sent right after the post
The red join-request button of the mapped channel is ALWAYS the first button row.
"""
import html
from typing import Optional, Tuple

from loguru import logger
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import Bot
from config import Vars
from .base import retry_on_flood
from .db import database
from .poster import make_poster
from .style import Raw

DEFAULT_TEXT = "<b>{manga_title}</b> {word} <b>{chapter_num}</b> added, read now"


def _danger_style():
    try:
        from pyrogram.enums import ButtonStyle
        return ButtonStyle.DANGER
    except Exception:
        return None


def red_button(text: str, url: str) -> InlineKeyboardButton:
    style = _danger_style()
    if style is not None:
        try:
            return InlineKeyboardButton(text, url=url, style=style)
        except TypeError:  # library without `style`
            pass
    return InlineKeyboardButton(text, url=url)


def build_markup(invite_link: Optional[str], post_link: Optional[str] = None, extra: Optional[InlineKeyboardMarkup] = None):
    rows = []
    if invite_link:
        rows.append([red_button("◉ Join Channel (request)", invite_link)])
    if extra is not None:
        rows.extend(extra.inline_keyboard)
    return InlineKeyboardMarkup(rows) if rows else None


def build_caption(info: dict) -> str:
    return DEFAULT_TEXT.format(
        manga_title=html.escape(str(info.get("title", ""))),
        word="chapters" if info.get("many") else "chapter",
        chapter_num=html.escape(str(info.get("chapter", ""))),
    )


def _int_or_str(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


async def update_channel_for(owner_id) -> Optional[object]:
    """The owner's Update Channel setting, else the UPDATE_CHANNEL env value, else None."""
    settings = await database.get_settings(owner_id) or {}
    value = settings.get("update_c") or Vars.UPDATE_CHANNEL
    if not value:
        try:
            from bot import DEFAULT_SETTINGS
            value = DEFAULT_SETTINGS.get("update_c") if Vars.IS_PRIVATE else None
        except Exception:
            value = None
    return _int_or_str(value) if value else None


def render(settings: dict, info: dict, invite: Optional[str], read_link: Optional[str]):
    """-> (caption, markup).  Pure function (tested): applies Update Text and Update Button."""
    from .uploaders import convert_button_format, convert_format

    repl = {
        "{manga_title}": info.get("title"), "{chapter_num}": info.get("chapter"),
        "{channel_title}": info.get("channel_title"), "{channel_link}": invite or "",
        "{read_link}": read_link or invite or "",
    }
    repl = {k: ("" if v is None else html.escape(str(v)) if k != "{channel_link}" and k != "{read_link}" else str(v))
            for k, v in repl.items()}

    text = settings.get("update_t")
    if text:
        for k, v in repl.items():
            text = str(text).replace(k, v)
        caption = convert_format(text)
    else:
        caption = build_caption(info)

    extra = None
    button_text = settings.get("update_b")
    if button_text:
        for k, v in repl.items():
            button_text = str(button_text).replace(k, v)
        extra = convert_button_format(button_text)
    return caption, build_markup(invite, read_link, extra)


async def announce_chapter(map_doc: dict, chapter_label: str, pages: int, post_message=None,
                           many: bool = False, target=None) -> Tuple[bool, str]:
    """Post the update card.  Returns (sent, reason_if_not).  Never raises.
    `target` overrides the destination (settings test sends the preview to the user's DM)."""
    if not Vars.ANNOUNCE and target is None:
        return False, "announcements are switched off (ANNOUNCE=False)"

    owner = map_doc.get("owner_id")
    settings = await database.get_settings(owner) or {}
    dest = target if target is not None else await update_channel_for(owner)
    if not dest:
        return False, "no Update Channel is set - Settings > Update Channel"

    info = {
        "title": map_doc.get("title"), "chapter": chapter_label,
        "site": map_doc.get("site_name") or map_doc.get("site"),
        "poster": map_doc.get("poster"), "channel_title": map_doc.get("channel_title"),
        "pages": pages, "many": many, "description": map_doc.get("description", ""),
        "genres": map_doc.get("genres", []), "status": map_doc.get("series_status", ""),
    }
    try:
        read_link = getattr(post_message, "link", None) if post_message is not None else None
    except Exception:
        read_link = None

    invite = map_doc.get("invite_link")
    if not invite:  # the join-request button must always be there: create the link now if the mapping has none
        from . import chmap, chservice  # late import (chservice imports chpoller which imports this module)
        invite = await chservice.make_invite_link(int(map_doc["channel_id"]))
        if invite and map_doc.get("_id"):
            try:
                await chmap.update_map(map_doc["_id"], invite_link=invite)
            except Exception as err:
                logger.warning(f"could not store invite link: {err}")
        elif not invite:
            logger.warning(f"announce: no join-request link for channel {map_doc.get('channel_id')} "
                           "(give the bot the 'invite users' right)")

    caption, markup = render(settings, info, invite, read_link)
    caption = Raw(caption)           # the owner's own wording: never restyled

    try:
        poster = await make_poster(info)
    except Exception as err:
        logger.warning(f"poster failed: {err}")
        poster = None

    try:
        if poster:
            try:
                await retry_on_flood(Bot.send_photo)(dest, poster, caption=caption, reply_markup=markup)
            except Exception as err:  # bad image etc. -> text only
                logger.warning(f"announce photo failed ({err}); sending text instead")
                await retry_on_flood(Bot.send_message)(dest, caption, reply_markup=markup)
        else:
            await retry_on_flood(Bot.send_message)(dest, caption, reply_markup=markup)
    except Exception as err:
        logger.warning(f"announce failed: {err}")
        return False, f"could not post in the update channel ({type(err).__name__}: {str(err)[:100]})"

    sticker = settings.get("update_s")
    if sticker:
        try:
            await retry_on_flood(Bot.send_sticker)(dest, sticker)
        except Exception as err:
            logger.warning(f"update sticker failed: {err}")
    return True, ""

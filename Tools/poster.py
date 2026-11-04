"""Poster hook for the updates-channel announcement.

`make_poster(info)` returns what `Bot.send_photo` accepts (a local file path or an
image URL), or None for a text-only post.  The default simply re-uses the series cover.

To plug in your own poster designer, create `Tools/poster_custom.py` with

    async def make_poster(info: dict) -> str | None: ...

`info` keys: title, chapter, site, poster (cover URL or None), channel_title, pages.
If your function raises or returns None the default cover is used, so a broken
designer can never block an announcement.
"""
from typing import Optional

from loguru import logger

try:  # optional, user supplied
    from Tools.poster_custom import make_poster as _custom_make_poster  # type: ignore
except ModuleNotFoundError:  # no custom designer installed
    _custom_make_poster = None
except Exception as _err:     # present but broken -> fall back to the cover
    logger.warning(f"Tools.poster_custom could not be imported: {_err}")
    _custom_make_poster = None


async def make_poster(info: dict):
    if _custom_make_poster is not None:
        try:
            result = await _custom_make_poster(info)
            if result:
                return result
        except Exception as err:
            logger.warning(f"poster_custom.make_poster failed, using the cover instead: {err}")
    return info.get("poster") or None

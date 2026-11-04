"""Your poster design (Tools/poster_design.py) wired to the new-chapter announcement.

`make_poster(info)` is called by Tools/poster.py.  `info` has: title, chapter, site, poster (cover URL),
channel_title, pages.  The design expects an AniList-style `meta` dict, so the chapter data is mapped onto it:

  title            -> manga name
  studio line      -> the site name (e.g. MGEKO)
  synopsis box     -> "Chapter N of <title> has just been added ..."
  pill button      -> NEW CHAPTER
  bottom stat row  -> "CHAPTER N" and "<pages> PAGES"-style chips are shown through format/status
"""
import asyncio
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests as http
from loguru import logger

from config import Vars
from Tools.poster_design import create_poster

BUTTON_TEXT = "NEW CHAPTER"


_COVER_CACHE: dict = {}          # url -> bytes (a series posts many chapters; fetch the cover once)


def _valid_image(data: Optional[bytes]) -> bool:
    if not data or data[:4] in (b"<!DO", b"<htm", b"<HTM"):
        return False
    try:
        from io import BytesIO
        from PIL import Image
        Image.open(BytesIO(data)).verify()
        return True
    except Exception:
        return False


def _fetch_cover(url: Optional[str]) -> Optional[bytes]:
    """Best-effort cover download (blocking; run in a thread).  Tries a browser-like client first, then
    cloudscraper (Cloudflare).  Only a real, decodable image is accepted.  None -> colour placeholder."""
    if not url or not str(url).startswith("http"):
        return None
    if url in _COVER_CACHE:
        return _COVER_CACHE[url]
    parts = urlparse(url)
    headers = {"Referer": f"{parts.scheme}://{parts.netloc}/", "User-Agent":
               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
               "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    attempts = []

    def curl():
        try:
            return http.get(url, headers=headers, timeout=30, impersonate="chrome")
        except TypeError:
            return http.get(url, headers=headers, timeout=30)

    def cloud():
        from cloudscraper import create_scraper
        return create_scraper().get(url, headers=headers, timeout=30)

    for name, fn in (("curl", curl), ("cloudscraper", cloud)):
        try:
            response = fn()
            if response.status_code == 200 and _valid_image(response.content):
                if len(_COVER_CACHE) > 60:
                    _COVER_CACHE.pop(next(iter(_COVER_CACHE)))
                _COVER_CACHE[url] = response.content
                return response.content
            attempts.append(f"{name}: HTTP {response.status_code}")
        except Exception as err:
            attempts.append(f"{name}: {type(err).__name__}")
    logger.warning(f"poster cover could not be downloaded from {url} ({'; '.join(attempts)})")
    return None


def build_meta(info: dict) -> dict:
    series = str(info.get("title") or "Unknown")
    title = series                                 # big title = the series; the channel brand sits in the tag above it
    chapter = str(info.get("chapter") or "?")
    many = bool(info.get("many"))
    site = Vars.POSTER_TITLE
    description = str(info.get("description") or "").strip() or f"{'Chapters' if many else 'Chapter'} {chapter} {'are' if many else 'is'} out now."
    genres = [str(g).strip() for g in (info.get("genres") or []) if str(g).strip()][:3]
    return {
        "title": {"english": title},
        "studios": {"nodes": [{"name": site}]} if site else {},
        "format": f"{'Chapters' if many else 'Chapter'} {chapter}",
        "status": "New",
        "genres": genres,
        "description": description,
    }


def _render(info: dict):
    cover = _fetch_cover(info.get("poster"))
    return create_poster(build_meta(info), cover_bytes=cover, button_text=BUTTON_TEXT)


async def make_poster(info: dict):
    """Returns a BytesIO JPEG (Bot.send_photo accepts it)."""
    return await asyncio.to_thread(_render, info)

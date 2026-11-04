"""Series details (cover, description, genres) for ANY supported site, read from the series page itself.

Used when a scraper did not return them (all six sites are covered by the same generic rules):
  cover        og:image / twitter:image            (made absolute)
  description  the longest of: description blocks of the usual themes, og:description, meta description
  genres       links to /genre(s)/ or /tag/ pages, itemprop=genre
"""
import asyncio
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

_DESC_SELECTORS = [
    ".summary__content", ".description-summary", ".dsct", "#description", "[itemprop=description]",
    ".manga-summary", ".summary-content", ".entry-content p", ".description", "#synopsis", ".synopsis",
]
_GENRE_HREF = re.compile(r"/(genres?|tags?|manga-genre|category)/[^/?#]+", re.I)
_JUNK = re.compile(r"^(read|first|last|latest|new|all|more|home|login|register|bookmark)\b", re.I)


_COVER_HINT = re.compile(r"cover|poster|thumb|summary_image|series-image|manga-image", re.I)
_CARD_HINT = re.compile(r"/og[-_/]|opengraph|og-image|social|share|banner|logo|favicon|avatar", re.I)


def _img_src(img) -> str:
    for attr in ("data-src", "data-lazy-src", "data-original", "src"):
        val = (img.get(attr) or "").strip()
        if val and not val.startswith("data:"):
            return val
    return ""


def pick_cover(bs, url: str, title: str = "") -> Optional[str]:
    """The series' REAL cover.  og:image is often a social card of the page (title text drawn on it), so a cover
    image on the page wins: alt = title, or a cover/poster/thumb hint in the url/class/parent; og:image last."""
    t = (title or "").strip().lower()
    scored = []
    for i, img in enumerate(bs.find_all("img")):
        src = _img_src(img)
        if not src or _CARD_HINT.search(src):
            continue
        alt = (img.get("alt") or "").strip().lower()
        hint = " ".join([src, " ".join(img.get("class") or []), " ".join(img.parent.get("class") or []) if img.parent else ""])
        score = 0
        if t and alt and (alt == t or t in alt or alt in t):
            score += 4
        if _COVER_HINT.search(hint):
            score += 3
        if score:
            scored.append((-score, i, src))
    if scored:
        scored.sort()
        return urljoin(url, scored[0][2])
    for prop in ("og:image", "twitter:image"):
        tag = bs.find("meta", attrs={"property": prop}) or bs.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            return urljoin(url, tag["content"].strip())
    return None


def parse_details(html: str, url: str) -> dict:
    out = {"poster": None, "description": "", "genres": [], "status": ""}
    if not html:
        return out
    bs = BeautifulSoup(html, "html.parser")

    h1 = bs.find("h1")
    out["poster"] = pick_cover(bs, url, h1.get_text(" ", strip=True) if h1 else "")

    candidates = []
    for sel in _DESC_SELECTORS:
        for node in bs.select(sel)[:3]:
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if len(text) > 40:
                candidates.append(text)
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = bs.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            candidates.append(re.sub(r"\s+", " ", tag["content"]).strip())
    if candidates:
        out["description"] = max(candidates, key=len)[:900]

    genres = []
    for a in bs.find_all("a", href=True):
        if _GENRE_HREF.search(a["href"]):
            text = a.get_text(" ", strip=True)
            if 2 <= len(text) <= 24 and not _JUNK.match(text) and text.lower() not in (g.lower() for g in genres):
                genres.append(text)
    for node in bs.select("[itemprop=genre]"):
        text = node.get_text(" ", strip=True)
        if text and text.lower() not in (g.lower() for g in genres):
            genres.append(text)
    out["genres"] = genres[:6]
    return out


def _fetch_html(url: str) -> str:
    from curl_cffi import requests as http
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    try:
        r = http.get(url, headers=headers, timeout=30, impersonate="chrome")
        if r.status_code == 200 and r.text:
            return r.text
    except Exception as err:
        logger.debug(f"details: curl failed for {url}: {err}")
    try:
        from cloudscraper import create_scraper
        r = create_scraper().get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.text
    except Exception as err:
        logger.debug(f"details: cloudscraper failed for {url}: {err}")
    return ""


async def fetch_details(url: str) -> dict:
    html = await asyncio.to_thread(_fetch_html, url)
    return parse_details(html, url)

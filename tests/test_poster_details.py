import asyncio
import io

import pytest
from PIL import Image

import Webs.asurascans as asura
import Webs.manga18fx as fx
from Tools import chmap
from Tools.poster_custom import build_meta, _fetch_cover, _valid_image
from tests.test_pipeline import server, fast_retries  # noqa: F401


class FakeScraper:
    html = ""

    def __init__(self, *a, **k): pass
    async def get(self, *a, **k): return FakeScraper.html


ASURA = """<html><head><meta property="og:image" content="/covers/blade.webp">
<meta property="og:description" content="A swordsman returns."></head><body>
<div class="divide-y divide-white/5"><a href="/series/x/chapter/2"><span><span>Chapter</span> 2</span></a></div>
</body></html>"""

FX = """<html><body><div class="summary_image"><img src="data:image/gif;base64,R0lGOD" data-src="/img/cover.jpg"></div>
<div class="genres-content"><a>Action</a>, <a>Adult</a></div><div class="dsct">A long story.</div>
<ul class="row-content-chapter"><li class="a-h"><a href="/manga/x/chapter-2">Chapter 2</a></li></ul></body></html>"""


async def test_asura_returns_absolute_cover_description_and_chapter_details(monkeypatch):
    monkeypatch.setattr(asura, "Scraper", FakeScraper)
    FakeScraper.html = ASURA
    web = asura.AsuraScansWebs()
    data = await web.get_chapters({"url": "https://asurascans.com/series/x", "title": "X"})
    chapters = web.iter_chapters(data)
    assert chapters and chapters[0]["poster"] == "https://asurascans.com/covers/blade.webp"
    assert chapters[0]["description"] == "A swordsman returns."
    assert chmap.details_from(chapters)["poster"].startswith("https://asurascans.com/")


async def test_manga18fx_cover_skips_lazy_placeholder_and_reads_genres(monkeypatch):
    web = fx.Manga18fxWebs()

    async def get(url): return FX
    monkeypatch.setattr(web, "get", get)
    data = await web.get_chapters({"url": "https://manga18fx.com/manga/x", "title": "X"})
    ch = web.iter_chapters(data)[0]
    assert ch["poster"] == "https://manga18fx.com/img/cover.jpg"          # data-src, not the data: placeholder
    assert ch["genres"] == ["Action", "Adult"] and ch["description"] == "A long story."


def test_poster_meta_has_chapter_line_description_and_genres():
    meta = build_meta({"title": "T", "chapter": "1-6", "many": True, "site": "Asura",
                       "description": "Long story here.", "genres": ["Action", "Fantasy", "Drama", "Extra"]})
    assert meta["description"].startswith("Long story here.")
    assert meta["title"]["english"] == "T" and meta["studios"]["nodes"][0]["name"] == "MMWC VOID"
    assert meta["genres"] == ["Action", "Fantasy", "Drama"] and meta["format"] == "Chapters 1-6"
    single = build_meta({"title": "T", "chapter": "7"})
    assert single["description"].startswith("Chapter 7 is out now.")


def test_cover_is_downloaded_validated_and_html_is_rejected(server):
    data = _fetch_cover(f"{server}/ok/1")              # the test server returns a real PNG
    assert data and _valid_image(data)
    assert _fetch_cover(f"{server}/cf") is None        # a Cloudflare HTML page is not a cover
    assert not _valid_image(b"<html>nope</html>")


async def test_details_are_stored_on_new_mapping_and_filled_for_old_ones(monkeypatch):
    from tests.test_chmap import FakeWeb, FakeChat, add_doc, use_web, clean_state  # noqa
    from Tools import chservice, chpoller

    class W(FakeWeb):
        def iter_chapters(self, data, page=1):
            return [{**c, "description": "Plot.", "genres": ["Action"], "status": "Ongoing"}
                    for c in super().iter_chapters(data, page)]
    use_web(monkeypatch, W())
    res = await chservice.create_mapping("S", "https://www.mgeko.cc/manga/s/", -1001234567890, 222, bot=FakeChat(-1001234567890))
    assert res["doc"]["description"] == "Plot." and res["doc"]["genres"] == ["Action"]

    old = await add_doc(series_url="https://www.mgeko.cc/manga/old/", posted=("1", "2", "3"))   # legacy: no details
    await chpoller.check_map(old)
    got = await chmap.get_map(old["_id"])
    assert got["description"] == "Plot." and got["genres"] == ["Action"] and got["poster"]


def test_generic_details_parser_reads_cover_description_genres():
    from Tools.details import parse_details
    html = """<html><head><meta property="og:image" content="/c/cover.jpg">
    <meta property="og:description" content="Short."></head><body>
    <div class="summary__content">A very long synopsis of the series that goes on well past forty characters.</div>
    <a href="/genre/action">Action</a><a href="/genre/fantasy">Fantasy</a><a href="/genre/action">Action</a>
    <a href="/read/1">Read</a></body></html>"""
    d = parse_details(html, "https://site.com/series/x")
    assert d["poster"] == "https://site.com/c/cover.jpg"
    assert d["description"].startswith("A very long synopsis")
    assert d["genres"] == ["Action", "Fantasy"]


@pytest.mark.parametrize("name", ["weebcentral", "mgeko", "manhwa18", "18fx", "asura", "manhuaplus"])
def test_all_six_sources_are_accepted_by_add(name):
    from TG.add_manage import parse_add
    out = parse_add("-1001234567890 %s https://x.com/series/a batch" % name)
    assert out[1] in ("weebc", "mgeko", "ma18", "18fx", "as", "mhpu")


async def test_ensure_details_fills_legacy_mapping_once(monkeypatch):
    from Tools import chpoller, chmap, details
    saved = {}

    async def fake_fetch(url):
        return {"poster": "https://x/c.jpg", "description": "Real synopsis text.", "genres": ["Action"], "status": ""}

    async def fake_update(mid, **f):
        saved.update(f)
        return True
    monkeypatch.setattr(details, "fetch_details", fake_fetch)
    monkeypatch.setattr(chmap, "update_map", fake_update)
    doc = await chpoller.ensure_details({"_id": 5, "series_url": "https://x/s"})
    assert doc["description"] == "Real synopsis text." and saved["genres"] == ["Action"]


def test_cover_prefers_real_cover_over_og_social_card():
    from Tools.details import parse_details
    html = """<html><head><meta property="og:image" content="https://s.com/og/card.png"></head><body><h1>The Grand Duke</h1>
    <img src="/logo.png"><img alt="The Grand Duke" src="https://cdn.s.com/covers/duke.webp"></body></html>"""
    assert parse_details(html, "https://s.com/x")["poster"] == "https://cdn.s.com/covers/duke.webp"

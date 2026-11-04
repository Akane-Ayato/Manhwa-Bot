import http.server
import io
import os
import threading
import zipfile

import PyPDF2
import pytest
from PIL import Image

import Tools.img2pdf as ip
from Tools.img2cbz import images_to_cbz
from Tools.img2pdf import ImageDownloadError, convert_images_to_pdf, download_and_convert_images


def make_png(w, h, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


COLORS = [(250, 10, 10), (10, 250, 10), (10, 10, 250), (250, 250, 10), (10, 250, 250), (250, 10, 250)]


class Handler(http.server.BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        if self.path.startswith("/ok/"):
            w = 300 if self.path.endswith("1") else 400
            body = make_png(w, 500)
            self.send_response(200); self.send_header("Content-Type", "image/png")
        elif self.path.startswith("/pg/"):
            import time
            n = int(self.path.rsplit("/", 1)[1])
            time.sleep((12 - n) * 0.04)            # later pages answer FIRST -> completion order is reversed
            body = make_png(300, 400, COLORS[n % len(COLORS)])
            self.send_response(200); self.send_header("Content-Type", "image/png")
        elif self.path == "/cf":
            body = b"<html>Attention Required! | Cloudflare</html>"
            self.send_response(200); self.send_header("Content-Type", "text/html")
        elif self.path == "/flaky" and Handler.hits[self.path] < 2:
            body = b"err"; self.send_response(503)
        elif self.path == "/flaky":
            body = make_png(300, 400); self.send_response(200); self.send_header("Content-Type", "image/png")
        else:
            body = b"nope"; self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(ip, "sleep", lambda s: None)
    Handler.hits.clear()


async def test_download_pages_in_order(server, tmp_path):
    urls = [f"{server}/ok/{i}" for i in range(1, 4)]
    files = await download_and_convert_images(urls, str(tmp_path / "pics"), server)
    assert [os.path.basename(f) for f in files] == ["00001.jpg", "00002.jpg", "00003.jpg"]
    assert all(os.path.getsize(f) > 0 for f in files)


async def test_download_retries_flaky_server(server, tmp_path):
    files = await download_and_convert_images([f"{server}/flaky"], str(tmp_path / "p"), server)
    assert len(files) == 1 and Handler.hits["/flaky"] == 2


async def test_download_failure_raises_and_stops_early(server, tmp_path):
    urls = [f"{server}/missing"] + [f"{server}/ok/{i}" for i in range(2, 40)]
    with pytest.raises(ImageDownloadError):
        await download_and_convert_images(urls, str(tmp_path / "p"), server)
    # remaining pages should mostly have been skipped (bandwidth), not all 39 fetched
    assert sum(v for k, v in Handler.hits.items() if k.startswith("/ok/")) < 39


async def test_cloudflare_page_is_not_saved_as_image(server, tmp_path):
    with pytest.raises(ImageDownloadError):
        await download_and_convert_images([f"{server}/cf"], str(tmp_path / "p"), server)


async def test_concurrency_is_limited(server, tmp_path, monkeypatch):
    active, peak = 0, 0
    lock = threading.Lock()
    real = ip.download_image

    def tracked(*a, **k):
        nonlocal active, peak
        with lock:
            active += 1; peak = max(peak, active)
        try:
            import time; time.sleep(0.05)
            return real(*a, **k)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(ip, "download_image", tracked)
    await download_and_convert_images([f"{server}/ok/{i}" for i in range(1, 25)], str(tmp_path / "p"), server)
    assert peak <= ip.MAX_CONCURRENT_DOWNLOADS


def _imgs(tmp_path, sizes):
    out = []
    for i, (w, h) in enumerate(sizes):
        p = tmp_path / f"{i:05}.jpg"
        Image.new("RGB", (w, h), (i * 40 % 255, 100, 100)).save(p, "JPEG")
        out.append(str(p))
    return out


def test_pdf_pages_widths_and_banners(tmp_path):
    imgs = _imgs(tmp_path, [(300, 500), (400, 600), (350, 700)])
    b1 = _imgs(tmp_path / "..", [(800, 200)])[0]
    out = str(tmp_path / "c.pdf")
    assert convert_images_to_pdf(imgs, out, str(tmp_path / "cmp"), None, 70, "https://t.me/x", b1, b1) is None
    r = PyPDF2.PdfReader(out)
    assert len(r.pages) == 5                          # 3 pages + 2 banners
    widths = {round(float(p.mediabox.width)) for p in r.pages}
    assert widths == {300}                            # everything scaled to the narrowest page
    # banner keeps its aspect (800x200 -> 300x75); the old code stretched it into a square
    assert round(float(r.pages[0].mediabox.height)) == 75
    assert not os.path.exists(tmp_path / "cmp")
    assert not any("_temp" in f for f in os.listdir(tmp_path))


def test_pdf_password(tmp_path):
    imgs = _imgs(tmp_path, [(300, 500)])
    out = str(tmp_path / "p.pdf")
    assert convert_images_to_pdf(imgs, out, str(tmp_path / "c"), "secret", 70) is None
    r = PyPDF2.PdfReader(out)
    assert r.is_encrypted
    assert r.decrypt("secret") != 0
    assert len(r.pages) == 1


def test_pdf_one_bad_page_fails_whole_chapter(tmp_path):
    imgs = _imgs(tmp_path, [(300, 500), (300, 500)])
    bad = tmp_path / "bad.jpg"; bad.write_bytes(b"not an image" * 100)
    out = str(tmp_path / "c.pdf")
    err = convert_images_to_pdf([imgs[0], str(bad), imgs[1]], out, str(tmp_path / "c"))
    assert isinstance(err, str) and "page 2" in err
    assert not os.path.exists(out) and not os.path.exists(tmp_path / "c")


def test_pdf_empty_returns_error(tmp_path):
    assert isinstance(convert_images_to_pdf([], str(tmp_path / "a.pdf"), str(tmp_path / "c")), str)


def test_pdf_page_k_is_image_k(tmp_path):
    """Each page is a distinct solid colour; page k of the PDF must show colour k (never 1,3,2)."""
    colours = [(250, 10, 10), (10, 250, 10), (10, 10, 250), (250, 250, 10), (10, 250, 250)]
    imgs = []
    for i, col in enumerate(colours):
        p = tmp_path / f"{i:05}.jpg"
        Image.new("RGB", (300, 400 + i * 40), col).save(p, "JPEG")      # different heights too
        imgs.append(str(p))
    out = str(tmp_path / "o.pdf")
    assert convert_images_to_pdf(imgs, out, str(tmp_path / "c")) is None
    r = PyPDF2.PdfReader(out)
    assert len(r.pages) == 5
    for i, page in enumerate(r.pages):
        assert round(float(page.mediabox.height)) == 400 + i * 40       # order check via geometry
        xobj = page["/Resources"]["/XObject"]
        raw = xobj[list(xobj.keys())[0]].get_object().get_data()          # embedded JPEG bytes
        px = Image.open(io.BytesIO(raw)).convert("RGB").getpixel((10, 10))
        assert all(abs(px[k] - colours[i][k]) < 40 for k in range(3)), (i, px)   # page i shows colour i


def test_pdf_width_most_common_and_capped(tmp_path):
    from Tools.img2pdf import pick_target_width
    assert pick_target_width([800, 800, 800, 300]) == 800          # one narrow page does not shrink the rest
    assert pick_target_width([1600, 1600, 900]) == 1200            # cap
    assert pick_target_width([300, 400]) == 300                    # tie -> smaller


def test_validate_rejects_tiny_and_truncated(tmp_path):
    from Tools.img2pdf import BadPageError, validate_image_file
    tiny = tmp_path / "t.png"; Image.new("RGB", (1, 1)).save(tiny)
    with pytest.raises(BadPageError):
        validate_image_file(str(tiny))
    good = tmp_path / "g.jpg"
    import random
    random.seed(1)
    im = Image.effect_noise((400, 600), 80).convert("RGB"); im.save(good, "JPEG")
    assert validate_image_file(str(good)) == (400, 600)
    cut = tmp_path / "c.jpg"; cut.write_bytes(good.read_bytes()[:3000])
    with pytest.raises(BadPageError):
        validate_image_file(str(cut))


def test_pdf_filename_with_pdf_in_dir(tmp_path):
    d = tmp_path / "x.pdf.dir"; d.mkdir()
    imgs = _imgs(tmp_path, [(300, 500)])
    out = str(d / "ch.pdf")
    assert convert_images_to_pdf(imgs, out, str(tmp_path / "c")) is None and os.path.exists(out)


def test_cbz(tmp_path):
    imgs = _imgs(tmp_path, [(10, 10), (10, 10)])
    out = str(tmp_path / "c.cbz")
    assert images_to_cbz(imgs, out) is None
    assert zipfile.ZipFile(out).namelist() == ["00000.jpg", "00001.jpg"]
    assert isinstance(images_to_cbz(["/nonexistent.jpg"], str(tmp_path / "d.cbz")), Exception)
    assert not os.path.exists(tmp_path / "d.cbz")


async def test_pages_keep_order_even_when_downloads_finish_out_of_order(server, tmp_path):
    n = 12
    urls = [f"{server}/pg/{i}" for i in range(n)]
    files = await download_and_convert_images(urls, str(tmp_path / "p"), server)
    assert len(files) == n
    for i, f in enumerate(files):
        with Image.open(f) as im:
            px = im.convert("RGB").getpixel((5, 5))
        want = COLORS[i % len(COLORS)]
        assert all(abs(px[k] - want[k]) < 5 for k in range(3)), f"file {i} holds the wrong page"
    out = str(tmp_path / "c.pdf")
    assert convert_images_to_pdf(files, out, str(tmp_path / "cmp")) is None
    assert len(PyPDF2.PdfReader(out).pages) == n

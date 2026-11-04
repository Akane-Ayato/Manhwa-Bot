"""
This module provides functions to download, convert, and compress images, and then convert them into a PDF file.
Modified:- Dra-Sama
"""
from typing import Optional

from urllib.parse import quote
from PIL import Image, ImageFile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from loguru import logger
import os

import pillow_avif  # This registers AVIF format support with Pillow
import pillow_heif

try:
    pillow_heif.register_heif_opener()  # importing alone does NOT enable .heic/.heif reading
except Exception as _err:  # pragma: no cover
    logger.warning(f"HEIF support unavailable: {_err}")

from curl_cffi import requests

import shutil

from cloudscraper import create_scraper
import asyncio

import PyPDF2
import gc
from time import sleep


from Webs.scraper import Scraper


ImageFile.LOAD_TRUNCATED_IMAGES = False

tor_proxies = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050",
}

class ImageDownloadError(Exception):
    pass


def get_headers(base_url: str):
    if "manhuaplus.com" in base_url:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://manhuaplus.com/",
            #"Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }

    elif "mangakatana.com" in base_url:
        headers = {
            "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            #"accept-encoding": "gzip, deflate, br, zstd"
            "accept-language": "en-GB,en;q=0.8",
            "connection": "keep-alive",
            #host: i.supernova22.click
            "referer": "https://mangakatana.com/",
            "sec-fetch-storage-access": "none",
            "sec-gpc": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        }
    elif "mangakakalot.gg" in base_url:
        headers = {
            "authority": "imgs-2.2xstorage.com",
            "method": "GET",
            "scheme": "https",
            "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": "https://www.manganato.gg/",
            "sec-ch-ua": '"Chromium";v="137", "Not(A)Brand";v="24"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "sec-fetch-dest": "image",
            "sec-fetch-mode": "no-cors",
            "sec-fetch-site": "cross-site",
            "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
        }
    else:
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": base_url,
        }

    return headers


async def thumbnali_images(image_url, download_dir, base_url = None, quality=80, file_name="thumb.jpg"):
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    headers = get_headers(base_url) if base_url else {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    try:
        return await asyncio.to_thread(download_image, file_name, image_url, download_dir, cs=True, headers=headers)
    except Exception:
        return None



_scraper = create_scraper()
_session = requests.Session()

MAX_CONCURRENT_DOWNLOADS = 5
DOWNLOAD_ATTEMPTS = 5
_IMAGE_EXT_FALLBACK = ".jpg"


def _not_an_image_reason(response) -> Optional[str]:
    """If the reply is a web page / JSON instead of an image, say why (else None).

    The body of a streamed response must be read explicitly - `.text` is empty
    until then, which is why the old Cloudflare check never triggered."""
    ctype = str(response.headers.get("content-type", "")).lower()
    if not ctype.startswith(("text/", "application/json")):
        return None
    body = b"".join(response.iter_content(1024))[:4000].decode("utf-8", "ignore")
    if "Attention Required! | Cloudflare" in body or "cf-browser-verification" in body:
        return "Cloudflare protection triggered"
    return f"Expected an image but got {ctype.split(';')[0]}"


MIN_PAGE_PIXELS = 50          # anything smaller is a tracking pixel / placeholder, not a page
MIN_PAGE_BYTES = 100
PDF_MAX_WIDTH = 1200


class BadPageError(Exception):
    pass


def validate_image_file(path: str) -> tuple:
    """Check that `path` is a real, fully decodable image.  Returns (width, height) or raises BadPageError."""
    try:
        if os.path.getsize(path) < MIN_PAGE_BYTES:
            raise BadPageError("file too small to be a page")
        with Image.open(path) as probe:
            probe.verify()                     # structure check
        with Image.open(path) as img:
            img.load()                         # full decode (catches truncated files)
            w, h = img.size
    except BadPageError:
        raise
    except Exception as err:
        raise BadPageError(f"not a valid image ({type(err).__name__})")
    if w < MIN_PAGE_PIXELS or h < MIN_PAGE_PIXELS:
        raise BadPageError(f"image too small ({w}x{h})")
    return w, h


def download_image(
    idx: str, image_url: str, download_dir: str,
    headers: Optional[dict] = None, cs: bool = False,
):
    """Download one image to `{download_dir}/{idx:05}.jpg` (blocking - run it in a thread).

    Retries with back-off; the last attempts go through Tor.  Raises on failure.
    """
    global _session, _scraper

    idx = str(idx).zfill(5)
    img_path = os.path.join(download_dir, f"{idx}{_IMAGE_EXT_FALLBACK}")

    if str(image_url).startswith("file://"):          # local sample pages (Settings > Test Settings)
        os.makedirs(download_dir, exist_ok=True)
        shutil.copyfile(str(image_url)[7:], img_path)
        validate_image_file(img_path)
        return str(img_path)

    session = _scraper if cs else _session
    last_error = None

    for attempt in range(DOWNLOAD_ATTEMPTS):
        kwargs = {"stream": True, "headers": headers, "timeout": 50}
        if attempt > 3:  # last resort: go through tor
            kwargs["proxies"] = tor_proxies

        response = None
        try:
            # (no `with`: curl_cffi responses are not context managers)
            response = session.get(image_url, **kwargs)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            reason = _not_an_image_reason(response)
            if reason:
                raise Exception(reason)

            if not os.path.exists(download_dir):
                raise Exception("Tasks cancelled")  # task was deleted meanwhile

            written = 0
            with open(img_path, "wb") as img_file:
                for chunk in response.iter_content(1024 * 64):
                    if chunk:
                        img_file.write(chunk)
                        written += len(chunk)

            if written == 0:
                raise Exception("Empty image body")

            validate_image_file(img_path)   # a corrupt/truncated page is retried, never kept

            return str(img_path)

        except Exception as err:
            last_error = err
            if str(err) == "Tasks cancelled":
                break
            sleep(3 * (attempt + 1))
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    if os.path.exists(img_path):
        try:
            os.remove(img_path)
        except OSError:
            pass

    raise Exception(f"Failed to download image {image_url}: {last_error}")


async def download_and_convert_images(
    images,
    download_dir,
    base_url: str,
    quality: int = 70,
    cs: bool = False,
    headers: Optional[dict] = None,
    pw: bool = False,
    on_progress=None,
):
    """Download all `images` (max MAX_CONCURRENT_DOWNLOADS at a time) and return their paths in page order.

    `on_progress(done, total)` (sync, optional) is called after every finished page."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)  # one per call, shared by all its images
    failed = False
    finished = 0
    total_pages = len(images)

    async def one(*args, **kwargs):
        nonlocal failed, finished
        async with semaphore:
            if failed:  # a page already failed -> don't waste bandwidth on the rest
                raise ImageDownloadError("skipped: another page failed")
            try:
                result = await asyncio.to_thread(download_image, *args, **kwargs)
            except Exception:
                failed = True
                raise
            finished += 1
            if on_progress is not None:
                try:
                    on_progress(finished, total_pages)
                except Exception:  # a broken progress callback must never fail a download
                    pass
            return result

    os.makedirs(download_dir, exist_ok=True)

    headers = headers or get_headers(base_url)

    process_list = await asyncio.gather(
        *(
            one(str(idx), image_url, download_dir, headers=headers, cs=cs)
            for idx, image_url in enumerate(images, 1)
        ),
        return_exceptions=True,
    )

    errors = [r for r in process_list if isinstance(r, BaseException)]
    if errors:
        # report the real cause, not a "skipped" marker
        real = next((e for e in errors if "skipped" not in str(e)), errors[0])
        raise ImageDownloadError(real)

    picturesList = [str(file) for file in process_list]   # gather() keeps the INPUT order == page order
    if len(picturesList) != total_pages:
        raise ImageDownloadError(f"page count mismatch: {len(picturesList)} of {total_pages}")

    gc.collect()

    return picturesList


def pick_target_width(widths, cap: int = PDF_MAX_WIDTH) -> int:
    """Most common page width (ties -> the smaller one), never wider than `cap`."""
    from collections import Counter
    counts = Counter(widths)
    best = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return min(best, cap)


def _prepare_page(src: str, dst: str, target_width: int, quality: int):
    """Re-encode one image as JPEG at `target_width`.  Returns (path, width, height) of the result."""
    with Image.open(src) as im:
        img = im.convert("RGB")
    w, h = img.size
    if w != target_width:
        img = img.resize((target_width, max(int(h * target_width / w), 1)), Image.LANCZOS)
    img.save(dst, "JPEG", quality=quality, optimize=True)
    return dst, img.size[0], img.size[1]


def convert_images_to_pdf(
    image_files, pdf_output_path,
    compressed_dir, password=None,
    compression_quality=85, hyperLink=None,
    banner1=None, banner2=None,
):
    """Build a PDF: EXACTLY one page per image, in the order given (banner first, closing banner last).

    Strict: a single unreadable page fails the whole chapter (a PDF with a missing page is worse
    than no PDF).  The result is reopened and its page count compared with the expectation.
    Returns None on success or an error string (the contract cworker relies on)."""
    if not image_files:
        return "No images provided for PDF conversion."

    os.makedirs(compressed_dir, exist_ok=True)
    pdf_output_path = str(pdf_output_path)
    root, _ext = os.path.splitext(pdf_output_path)
    temp_pdf_path = f"{root}_temp.pdf"

    def cleanup():
        shutil.rmtree(compressed_dir, ignore_errors=True)
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

    sequence = ([("b1", banner1)] if banner1 else []) + \
               [(f"p{n:05}", f) for n, f in enumerate(image_files)] + \
               ([("b2", banner2)] if banner2 else [])

    # pass 1: every file must be a valid image; remember widths
    sizes = []
    for n, (tag, path) in enumerate(sequence):
        try:
            sizes.append(validate_image_file(path))
        except BadPageError as err:
            cleanup()
            where = "banner" if tag.startswith("b") else f"page {int(tag[1:]) + 1}"
            return f"{where} is unusable: {err}"

    body_widths = [w for (w, _h), (tag, _p) in zip(sizes, sequence) if not tag.startswith("b")]
    target_width = pick_target_width(body_widths)

    try:
        c = canvas.Canvas(temp_pdf_path, pagesize=letter)
        for n, (tag, path) in enumerate(sequence):
            cf = os.path.join(compressed_dir, f"{n:05}.jpg")
            res, w, h = _prepare_page(path, cf, target_width, compression_quality)
            c.setPageSize((w, h))
            c.drawImage(res, 0, 0, width=w, height=h)
            if hyperLink and tag.startswith("b"):
                c.linkURL(url=hyperLink, rect=(0, 0, w, h), relative=0, thickness=0)
            c.showPage()
            os.remove(res)
        c.save()

        got = len(PyPDF2.PdfReader(temp_pdf_path).pages)   # verify what was REALLY written
        if got != len(sequence):
            cleanup()
            return f"PDF page count mismatch (expected {len(sequence)}, got {got})"
    except Exception as err:
        logger.error(f"PDF build failed: {err}")
        cleanup()
        return f"PDF build failed: {type(err).__name__}: {err}"

    shutil.rmtree(compressed_dir, ignore_errors=True)

    if password:
        err = encrypt_pdf(temp_pdf_path, pdf_output_path, password)
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
        if err:
            return err
    else:
        os.replace(temp_pdf_path, pdf_output_path)

    gc.collect()
    return None


def encrypt_pdf(input_path, output_path, password):
    """Encrypt a PDF with a password using PyPDF2.  Returns None or an error string."""
    try:
        with open(input_path, 'rb') as input_file:
            reader = PyPDF2.PdfReader(input_file)
            writer = PyPDF2.PdfWriter()

            for page in reader.pages:
                writer.add_page(page)

            writer.encrypt(user_password=password, owner_password=None,
                          use_128bit=True)

            with open(output_path, 'wb') as output_file:
                writer.write(output_file)
        return None

    except Exception as e:
        logger.error(f"Failed to encrypt PDF: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return f"Failed to password-protect the PDF: {e}"

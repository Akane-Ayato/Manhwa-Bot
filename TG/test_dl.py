"""
Test Download Command - /test_dl <chapter_url>
This command tests downloading a manga chapter from a URL to verify everything works.
"""
from pyrogram import filters
from pyrogram.types import InputMediaDocument

from bot import Bot, Vars, logger

from .storage import retry_on_flood, check_get_web, igrone_error, queue
from Tools.base import TaskCard
from Tools.db import database
from Tools.img2pdf import download_and_convert_images, convert_images_to_pdf

import os
import shutil
import asyncio


@Bot.on_message(filters.command("test_dl") & filters.private)
async def test_download_command(client, message):
    """
    Test download command for admins.
    Usage: /test_dl <chapter_url>
    """
    if not message.from_user or message.from_user.id not in Vars.ADMINS:
        return  # debugging tool: admins only (it used to be open to everyone)

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        return await message.reply(
            "<b>Usage:</b> <code>/test_dl &lt;chapter_url&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/test_dl https://www.mangamob.com/chapter/en/murim-psychopath-chapter-6-eng-li</code>"
        )

    chapter_url = args[1].strip()
    user_id = message.from_user.id

    # Find the appropriate scraper for this URL
    webs = check_get_web(chapter_url)
    if not webs:
        return await message.reply(
            "<b>✗ Error:</b> Could not find a scraper for this URL.\n"
            f"<b>URL:</b> <code>{chapter_url}</code>"
        )

    sts = await message.reply(
        f"<b>⌕ Testing download...</b>\n\n"
        f"<b>URL:</b> <code>{chapter_url}</code>\n"
        f"<b>Scraper:</b> <code>{webs.__class__.__name__}</code>\n"
        f"<b>Status:</b> <code>Getting pictures...</code>"
    )

    try:
        # Step 1: Get pictures from URL
        data = {"url": chapter_url, "title": "Test", "manga_title": "Test Manga"}
        pictures = await webs.get_pictures(chapter_url, data)

        if not pictures:
            return await sts.edit(
                f"<b>✗ Error:</b> No pictures found!\n\n"
                f"<b>URL:</b> <code>{chapter_url}</code>\n"
                f"<b>Scraper:</b> <code>{webs.__class__.__name__}</code>"
            )

        await sts.edit(
            f"<b>✓ Found {len(pictures)} images</b>\n\n"
            f"<b>URL:</b> <code>{chapter_url}</code>\n"
            f"<b>Status:</b> <code>Downloading images...</code>\n\n"
            f"<b>First image:</b>\n<code>{pictures[0][:100]}...</code>"
        )

        # Step 2: Download images
        main_dir = f"Process/test_{user_id}"
        download_dir = f"{main_dir}/pictures"
        compressed_dir = f"{main_dir}/compress"

        os.makedirs(download_dir, exist_ok=True)

        try:
            cs = getattr(webs, 'cs', False)
        except:
            cs = False

        downloads_list = await download_and_convert_images(
            pictures, download_dir, 
            webs.url, cs=cs
        )

        # Check download results
        successful = [f for f in downloads_list if f and os.path.exists(f)]
        failed = len(pictures) - len(successful)

        # Check file sizes
        sizes = []
        for f in successful:
            try:
                size = os.path.getsize(f)
                sizes.append(size)
            except:
                sizes.append(0)

        zero_size_count = sizes.count(0)

        await sts.edit(
            f"<b>⇩ Download Results:</b>\n\n"
            f"<b>Total Images:</b> <code>{len(pictures)}</code>\n"
            f"<b>Downloaded:</b> <code>{len(successful)}</code>\n"
            f"<b>Failed:</b> <code>{failed}</code>\n"
            f"<b>Zero Size Files:</b> <code>{zero_size_count}</code>\n\n"
            f"<b>Status:</b> <code>Converting to PDF...</code>"
        )

        if zero_size_count > 0:
            await sts.edit(
                f"<b>▲ Warning: {zero_size_count} files have 0 bytes!</b>\n\n"
                f"This usually means:\n"
                f"• CloudFlare protection is blocking downloads\n"
                f"• Image URLs are broken/expired\n"
                f"• Rate limiting from the website\n\n"
                f"<b>First few image URLs:</b>\n" +
                "\n".join([f"<code>{p[:80]}...</code>" for p in pictures[:3]])
            )
            # Cleanup
            shutil.rmtree(main_dir, ignore_errors=True)
            return

        # Step 3: Convert to PDF
        pdf_output_path = f"{main_dir}/test_chapter.pdf"

        result = convert_images_to_pdf(
            downloads_list, pdf_output_path,
            compressed_dir, password=None, 
            compression_quality=30, hyperLink=None
        )

        if result:
            await sts.edit(f"<b>✗ PDF Error:</b> {result}")
            shutil.rmtree(main_dir, ignore_errors=True)
            return

        # Step 4: Check PDF size
        pdf_size = os.path.getsize(pdf_output_path) if os.path.exists(pdf_output_path) else 0
        pdf_size_mb = pdf_size / (1024 * 1024)

        # Step 5: Send PDF
        await sts.edit("<b>⇧ Uploading PDF...</b>")

        await retry_on_flood(client.send_document)(
            message.chat.id,
            pdf_output_path,
            caption=(
                f"<b>✓ Test Download Complete!</b>\n\n"
                f"<b>Images:</b> <code>{len(pictures)}</code>\n"
                f"<b>PDF Size:</b> <code>{pdf_size_mb:.2f} MB</code>\n"
                f"<b>Scraper:</b> <code>{webs.__class__.__name__}</code>"
            ),
            reply_to_message_id=message.id
        )

        await sts.delete()

    except Exception as err:
        logger.exception(f"Test download error: {err}")
        await sts.edit(
            f"<b>✗ Error:</b> <code>{str(err)[:500]}</code>"
        )

    finally:
        # Cleanup
        if os.path.exists(f"Process/test_{user_id}"):
            shutil.rmtree(f"Process/test_{user_id}", ignore_errors=True)
"""/add  and  /manage  (alias /mange): connect a series to a channel and manage the connections.

/add <channel id> <source> <series url> <batch|latest> [custom title]
  batch  = upload every chapter that exists now (in order), then keep posting new ones
  latest = only chapters released from now on
Admin only.  /manage removal also wipes the mapping's queued tasks and failure records.
"""
import re
import secrets
from urllib.parse import urlparse

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import Bot, logger
from Tools import chmap, chpoller, chservice
from Tools.ui import edit_any
from Tools.base import igrone_error
from Tools.chmap import MapError
from TG.chmap_cmds import (admin_only, args_of, build_list, esc, info_markup, info_text, reply)

ADD_HELP = (
    "<b>✚ Connect a series to a channel</b>\n\n"
    "<code>/add &lt;channel id&gt; &lt;source&gt; &lt;series url&gt; &lt;batch|latest&gt; [title]</code>\n\n"
    "• <b>batch</b> - upload ALL chapters that exist now, then keep posting new ones "
    "(one announcement in the updates channel when the backlog is done)\n"
    "• <b>latest</b> - only chapters released from now on (each one announced)\n\n"
    "<b>Sources:</b> {sources}\n"
    "Example:\n<code>/add -1001234567890 asura https://asuracomic.net/series/solo-leveling batch</code>\n\n"
    "Add the bot to the channel as admin first (Post messages + Invite users)."
)

SOURCE_ALIASES = {
    "manga18fx": "18fx", "18fx": "18fx", "asura": "as", "asurascans": "as", "asurascan": "as", "as": "as",
    "weebcentral": "weebc", "weebc": "weebc", "weeb": "weebc", "mgeko": "mgeko", "manhwa18": "ma18", "ma18": "ma18",
    "manhuaplus": "mhpu", "mhpu": "mhpu",
}
SOURCE_NAMES = {"18fx": "manga18fx", "as": "asura", "weebc": "weebcentral", "mgeko": "mgeko", "ma18": "manhwa18", "mhpu": "manhuaplus"}
SOURCE_LABELS = [("18fx", "Manga18fx"), ("as", "Asura Scans"), ("weebc", "Weeb Central"),
                 ("mgeko", "Mgeko"), ("ma18", "Manhwa18"), ("mhpu", "Manhuaplus")]
_pending = {}      # retry token -> args (for the "I gave the rights" button)


def parse_add(text: str):
    """-> (channel_id, source_sf, url, mode, title|None); raises MapError."""
    tokens = (text or "").split()
    if len(tokens) < 4:
        raise MapError("Need: <channel id> <source> <series url> <batch|latest>")
    raw_chat, source, url, mode = tokens[0], tokens[1].lower(), tokens[2], tokens[3].lower()
    if not re.match(r"^-100\d{5,}$", raw_chat):
        raise MapError(f"Channel id must look like -1001234567890 (got `{raw_chat}`)")
    if source not in SOURCE_ALIASES:
        raise MapError("Unknown source `%s`. Use: %s" % (source, ", ".join(SOURCE_NAMES.values())))
    if not re.match(r"^https?://", url, re.I):
        raise MapError(f"Series url must start with http(s):// (got `{url}`)")
    if mode not in (chmap.MODE_BATCH, chmap.MODE_LATEST):
        raise MapError("Last word must be `batch` or `latest`")
    title = " ".join(tokens[4:]).strip() or None
    return int(raw_chat), SOURCE_ALIASES[source], url, mode, title


def title_from_url(url: str) -> str:
    slug = [p for p in urlparse(url).path.split("/") if p][-1:] or ["series"]
    slug = re.sub(r"-[0-9a-f]{6,}$", "", slug[0])            # asura appends a hash to slugs
    return re.sub(r"[-_]+", " ", slug).strip().title() or "Series"


async def run_add(message, args, edit=None):
    channel_id, sf, url, mode, title = args
    from TG.storage import web_data
    web = chmap.detect_site(url, web_data)
    if web is None or web.sf != sf:
        raise MapError("That URL does not belong to the chosen source")
    return await chservice.create_mapping(title or title_from_url(url), url, channel_id,
                                          message.from_user.id, mode=mode)


def _add_result(res, mode) -> str:
    doc = res["doc"]
    text = (f"✓ <b>Connected #{doc['_id']}</b>\n\n❖ {esc(doc['title'])}\n◍ {esc(res['site_name'])}\n"
            f"➥ {esc(doc['channel_title'])} (<code>{doc['channel_id']}</code>)\n"
            f"❖ {res['total_chapters']} chapters on the site, latest <b>{esc(res['latest'])}</b>\n")
    if mode == chmap.MODE_BATCH:
        text += f"❖ <b>Batch</b>: uploading all {res['total_chapters']} chapters one by one - watch /queue\n"
    else:
        text += "❖ <b>Latest</b>: only new chapters will be posted from now on.\n"
    text += "⌘ Join-request link: " + ("ready" if res["invite_ok"] else "<b>not created</b> (give the 'invite users' right)")
    return text


@Bot.on_message(filters.command("add") & filters.private & admin_only)
async def add_cmd(client, message):
    text = args_of(message)
    from TG.storage import web_data
    if not text:
        text_, kb = _source_panel()
        return await reply(message, text_, reply_markup=kb)
    try:
        args = parse_add(text)
    except MapError as err:
        return await reply(message, f"✗ {esc(err)}\n\nSend /add alone to see the format.")
    await _do_add(message, args)


async def _do_add(message, args, sts=None):
    sts = sts or await reply(message, "<i>Checking channel rights and the series page...</i>")
    try:
        res = await run_add(message, args)
    except MapError as err:
        reason = str(err)
        if any(w in reason.lower() for w in ("admin", "right", "member", "cannot see")):
            token = secrets.token_hex(4)
            _pending[token] = (message.from_user.id, args)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✓ I gave the rights - retry", callback_data=f"addr_{token}")]])
            return await igrone_error(sts.edit)(f"✗ {esc(reason)}\n\nFix it in the channel, then press the button.",
                                                 reply_markup=kb)
        return await igrone_error(sts.edit)(f"✗ {esc(reason)}")
    except Exception as err:
        logger.exception(f"/add failed: {err}")
        return await igrone_error(sts.edit)(f"✗ Unexpected error: <code>{esc(type(err).__name__)}: {esc(str(err)[:150])}</code>")
    await igrone_error(sts.edit)(_add_result(res, args[3]))


@Bot.on_callback_query(filters.regex(r"^addr_(\w+)$") & admin_only)
async def add_retry_cb(client, query):
    entry = _pending.get(query.matches[0].group(1))
    if not entry or entry[0] != query.from_user.id:
        return await query.answer("Expired - send /add again", show_alert=True)
    await query.answer("Checking again...")
    _pending.pop(query.matches[0].group(1), None)
    await edit_any(query, "<i>Checking channel rights and the series page...</i>")
    await _do_add(query, entry[1], sts=query.message)


# ----------------------------------------------------------------- /manage ---
@Bot.on_message(filters.command(["manage", "mange"]) & filters.private & admin_only)
async def manage_cmd(client, message):
    arg = args_of(message)
    if arg:
        doc, matches = await chservice.resolve(arg)
        if doc:
            return await reply(message, await info_text(doc), reply_markup=info_markup(doc))
    text, markup = await build_list(1)
    await reply(message, text, reply_markup=markup)


@Bot.on_callback_query(filters.regex(r"^chi_(\d+)$") & admin_only)
async def open_cb(client, query):
    doc = await chmap.get_map(int(query.matches[0].group(1)))
    if not doc:
        return await query.answer("Removed", show_alert=True)
    await edit_any(query, await info_text(doc), reply_markup=info_markup(doc))
    await query.answer()


@Bot.on_callback_query(filters.regex(r"^chf_(\d+)$") & admin_only)
async def retry_failed_cb(client, query):
    map_id = int(query.matches[0].group(1))
    n = await chpoller.reset_failures(map_id)
    await chmap._col().update_one({"_id": map_id}, {"$set": {"next_check": 0}})
    doc = await chmap.get_map(map_id)
    if doc and doc.get("state") == chmap.STATE_BATCH:
        await chpoller.refill_batch(map_id)
    await query.answer(f"Retrying {n} failed chapter(s)")
    if doc:
        await edit_any(query, await info_text(doc), reply_markup=info_markup(doc))


@Bot.on_callback_query(filters.regex(r"^chs_(\d+)$") & admin_only)
async def skip_failed_cb(client, query):
    map_id = int(query.matches[0].group(1))
    fails = await chpoller.list_failures(map_id)
    if not fails:
        return await query.answer("Nothing failed", show_alert=True)
    key = fails[0]["key"]
    await chmap.record_posted(map_id, key)
    await chpoller.clear_failure(map_id, key)
    doc = await chmap.get_map(map_id)
    if doc and doc.get("state") == chmap.STATE_BATCH:
        await chpoller.refill_batch(map_id)
    await query.answer(f"Skipped chapter {key}")
    if doc:
        await edit_any(query, await info_text(await chmap.get_map(map_id)), reply_markup=info_markup(doc))


# ----------------------------------------------------- guided /add (buttons) ---
def _source_panel():
    kb = InlineKeyboardMarkup([
        *[[InlineKeyboardButton(a[1], callback_data=f"adds_{a[0]}"), InlineKeyboardButton(b[1], callback_data=f"adds_{b[0]}")]
          for a, b in zip(SOURCE_LABELS[::2], SOURCE_LABELS[1::2])],
        [InlineKeyboardButton("Typed form", callback_data="addh"), InlineKeyboardButton("◂ Back", callback_data="chl_1_all")],
    ])
    return "<b>Add a manhwa</b>\n\nStep 1 of 3 - choose the <b>source site</b>:", kb


@Bot.on_callback_query(filters.regex(r"^adds_home$") & admin_only)
async def add_home_cb(client, query):
    text, kb = _source_panel()
    await edit_any(query, text, reply_markup=kb)
    await query.answer()


@Bot.on_callback_query(filters.regex(r"^mm_home$") & admin_only)
async def hub_cb(client, query):
    text, markup = await build_list(1)
    await edit_any(query, text, reply_markup=markup)
    await query.answer()


@Bot.on_callback_query(filters.regex(r"^addh$") & admin_only)
async def add_help_cb(client, query):
    await edit_any(query, ADD_HELP.format(sources=", ".join(SOURCE_NAMES.values())))
    await query.answer()


@Bot.on_callback_query(filters.regex(r"^adds_(\w+)$") & admin_only)
async def add_source_cb(client, query):
    sf = query.matches[0].group(1)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Batch: all chapters + new", callback_data=f"addm_{sf}_batch")],
        [InlineKeyboardButton("Latest: only new chapters", callback_data=f"addm_{sf}_latest")],
        [InlineKeyboardButton("Cancel", callback_data="kclose")],
    ])
    await edit_any(query, 
        "<b>Connect a series to a channel</b>\n\nStep 2 of 3 - choose the <b>mode</b>:\n\n"
        "<b>Batch</b> uploads every chapter that exists now (in order), then keeps posting new ones. "
        "One announcement when the backlog is done.\n"
        "<b>Latest</b> posts only chapters released from now on, one announcement each.", reply_markup=kb)
    await query.answer()


@Bot.on_callback_query(filters.regex(r"^addm_(\w+)_(batch|latest)$") & admin_only)
async def add_mode_cb(client, query):
    sf, mode = query.matches[0].group(1), query.matches[0].group(2)
    await query.answer()
    await edit_any(query, 
        f"<b>Step 3 of 3</b> - send ONE message with the <b>channel id</b> and the <b>series link</b> "
        f"(optionally a title after them):\n\n<code>-1001234567890 https://site.com/series/name</code>\n\n"
        f"Mode: <b>{mode}</b>. I wait 3 minutes. Make the bot admin in the channel first.")
    try:
        reply_msg = await client.listen(user_id=query.from_user.id, timeout=180, filters=filters.text)
    except Exception:
        return await edit_any(query, "Timed out. Send /add to start again.")
    tokens = (reply_msg.text or "").split()
    if len(tokens) < 2:
        return await reply(reply_msg, "I need the channel id and the link. Send /add to start again.")
    source = SOURCE_NAMES.get(sf, sf)
    try:
        args = parse_add(" ".join([tokens[0], source, tokens[1], mode] + tokens[2:]))
    except MapError as err:
        return await reply(reply_msg, f"✘ {esc(err)}\n\nSend /add to try again.")
    await _do_add(reply_msg, args)


# ------------------------------------------------ edit a connection (hub) ---
async def _refresh(query, map_id):
    doc = await chmap.get_map(map_id)
    if doc:
        await edit_any(query, await info_text(doc), reply_markup=info_markup(doc))


@Bot.on_callback_query(filters.regex(r"^chbb_(\d+)$") & admin_only)
async def batch_start_cb(client, query):
    map_id = int(query.matches[0].group(1))
    await query.answer("Reading the series page...")
    try:
        res = await chservice.start_batch(map_id)
        await query.answer(f"Batch started: {res['total']} chapters", show_alert=True)
    except MapError as err:
        await query.answer(str(err)[:190], show_alert=True)
    except Exception as err:
        await query.answer(f"{type(err).__name__}: {str(err)[:150]}", show_alert=True)
    await _refresh(query, map_id)


@Bot.on_callback_query(filters.regex(r"^chbs_(\d+)$") & admin_only)
async def batch_stop_cb(client, query):
    map_id = int(query.matches[0].group(1))
    await chservice.stop_batch(map_id)
    await query.answer("Batch stopped - only new chapters from now on", show_alert=True)
    await _refresh(query, map_id)


async def _ask(client, query, prompt: str):
    await edit_any(query, prompt)
    try:
        msg = await client.listen(user_id=query.from_user.id, timeout=120, filters=filters.text)
    except Exception:
        return None
    return msg


@Bot.on_callback_query(filters.regex(r"^chnm_(\d+)$") & admin_only)
async def rename_cb(client, query):
    map_id = int(query.matches[0].group(1))
    await query.answer()
    msg = await _ask(client, query, "<b>Rename</b>\n\nSend the new title (used in file names, captions and update posts).")
    if msg and msg.text and not msg.text.startswith("/"):
        await chmap.update_map(map_id, title=msg.text.strip()[:120])
    await _refresh(query, map_id)


@Bot.on_callback_query(filters.regex(r"^chcc_(\d+)$") & admin_only)
async def change_channel_cb(client, query):
    map_id = int(query.matches[0].group(1))
    await query.answer()
    msg = await _ask(client, query, "<b>Change channel</b>\n\nSend the new channel id (<code>-100...</code>). "
                                    "The bot must be admin there; waiting chapters are dropped.")
    if msg and msg.text:
        try:
            title = await chservice.change_channel(map_id, int(msg.text.strip()))
            await reply(msg, f"✓ Moved to <b>{esc(title)}</b>")
        except (MapError, ValueError) as err:
            await reply(msg, f"✗ {esc(err)}")
    await _refresh(query, map_id)

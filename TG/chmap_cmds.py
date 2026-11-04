"""Admin commands for channel mapping (/ch_map and friends).  Every command is admin-only."""
import html
import io
import time

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import Bot, Vars, logger
from Tools import chmap, chpoller, chservice
from Tools.ui import edit_any
from Tools.base import queue, retry_on_flood, igrone_error
from Tools.chmap import MapError

PAGE_SIZE = 12

MAP_HELP = (
    "<b>✦ Channel mapping</b>\n\n"
    "Auto-post a manhwa's new chapters into a channel.\n\n"
    "<b>Add:</b>\n<code>/ch_map &lt;manga name&gt; &lt;manga page url&gt; &lt;channel id&gt;</code>\n"
    "Example:\n<code>/ch_map Solo Leveling https://mgeko.cc/manga/solo-leveling/ -1001234567890</code>\n"
    "Add <code>--last 3</code> right after /ch_map to also post the newest 3 chapters now.\n\n"
    "<b>Before:</b> make a channel, add this bot as admin (post messages + invite users).\n"
    "<b>Sites:</b> {sites}\n\n"
    "<b>Manage:</b>\n"
    "/ch_list · /ch_info · /ch_pause · /ch_resume · /ch_remove\n"
    "/add · /manage\n/ch_check · /ch_backfill · /ch_failed · /ch_retry · /ch_skip\n"
    "/ch_edit · /ch_import · /ch_export · /ch_stats · /ch_sites"
)


def _is_admin(_, __, update):
    user = getattr(update, "from_user", None)
    return bool(user and user.id in Vars.ADMINS)


admin_only = filters.create(_is_admin)


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def ago(ts) -> str:
    if not ts:
        return "never"
    secs = max(0, int(time.time() - ts))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def status_icon(doc) -> str:
    return {"active": "●", "paused": "‖", "error": "◉"}.get(doc.get("status"), "○")


def args_of(message) -> str:
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def reply(message, text, **kw):
    return await retry_on_flood(message.reply_text)(text, disable_web_page_preview=True, **kw)


async def pick_one(message, query: str):
    """Resolve `<id|name>` to exactly one mapping, or tell the admin what to do."""
    if not query:
        await reply(message, "Give a mapping id or name, e.g. <code>/ch_info 17</code>")
        return None
    doc, matches = await chservice.resolve(query)
    if doc:
        return doc
    if not matches:
        await reply(message, f"No mapping found for <code>{esc(query)}</code>. See /ch_list")
        return None
    lines = "\n".join(f"<code>{m['_id']}</code> · {esc(m['title'])} → {esc(m['channel_title'])}" for m in matches[:15])
    await reply(message, f"{len(matches)} matches - use the id:\n{lines}")
    return None


# ------------------------------------------------------------------ /ch_map ---
def _split_last_flag(text: str):
    """`--last 3 rest...` -> (3, rest)"""
    tokens = text.split(maxsplit=2)
    if len(tokens) >= 3 and tokens[0] == "--last" and tokens[1].isdigit():
        return int(tokens[1]), tokens[2]
    return 0, text


@Bot.on_message(filters.command("ch_map") & filters.private & admin_only)
async def ch_map_cmd(client, message):
    text = args_of(message)
    if not text:
        from TG.storage import web_data
        return await reply(message, MAP_HELP.format(sites=esc(chmap.allowed_site_names(web_data))))

    last_n, text = _split_last_flag(text)
    try:
        name, url, channel_id = chmap.parse_map_args(text)
    except MapError as err:
        return await reply(message, f"✗ {esc(err)}\n\nSend /ch_map alone to see the format.")

    sts = await reply(message, "<i>Checking channel and manga page...</i>")
    try:
        res = await chservice.create_mapping(name, url, channel_id, message.from_user.id, last_n=last_n)
    except MapError as err:
        return await igrone_error(sts.edit)(f"✗ {esc(err)}")
    except Exception as err:
        logger.exception(f"/ch_map failed: {err}")
        return await igrone_error(sts.edit)(f"✗ Unexpected error: <code>{esc(type(err).__name__)}: {esc(str(err)[:150])}</code>")

    doc = res["doc"]
    text = (
        f"✓ <b>Mapped #{doc['_id']}</b>\n\n"
        f"❖ {esc(doc['title'])}\n"
        f"◍ {esc(res['site_name'])}\n"
        f"➥ {esc(doc['channel_title'])} (<code>{doc['channel_id']}</code>)\n"
        f"❖ {res['total_chapters']} chapters found, latest <b>{esc(res['latest'])}</b>\n"
    )
    if res["queued"]:
        text += f"⧖ {res['queued']} chapter(s) queued now\n"
    else:
        text += "➥ Only <b>new</b> chapters will be posted (existing ones are the baseline).\n"
    text += "⌘ Join-request link: " + ("created" if res["invite_ok"] else "<b>not created</b> (give the bot the 'invite users' right)")
    await igrone_error(sts.edit)(text)


# ----------------------------------------------------------------- /ch_list ---
async def build_list(page: int, status=None):
    docs = await chmap.list_maps(status=status)
    counts = await chmap.count_maps()
    total = len(docs)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    chunk = docs[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    head = ("<b>◈ MANHWA AUTO UPLOAD</b>\n"
            f"<blockquote>{total} series  ·  ● {counts.get('active', 0)} running  ·  ‖ {counts.get('paused', 0)} paused  ·  "
            f"◉ {counts.get('error', 0)} problem\nPage {page}/{pages}</blockquote>\n")
    if not chunk:
        return head + "\n<i>Nothing connected yet. Tap <b>+ Add Manhwa</b> below.</i>", InlineKeyboardMarkup([
            [InlineKeyboardButton("+ Add Manhwa", callback_data="adds_home"), InlineKeyboardButton("◂ Back", callback_data="target_channel")]])

    lines = []
    for d in chunk:
        lines.append(
            f"\n{status_icon(d)} <b>#{d['_id']}</b> {esc(d['title'])} · <code>{esc(d['site'])}</code>\n"
            f"   ↳ {esc(d['channel_title'])} · last <b>{esc(d.get('last_chapter') or '-')}</b> · "
            f"checked {ago(d.get('last_checked'))}"
            + (f"\n   ▲ {esc(d['last_error'])[:80]}" if d.get("last_error") else "")
        )
    tag = status or "all"
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◂ Prev", callback_data=f"chl_{page - 1}_{tag}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="just_kidding"))
    if page < pages:
        nav.append(InlineKeyboardButton("Next ▸", callback_data=f"chl_{page + 1}_{tag}"))
    opens = [InlineKeyboardButton(f"#{d['_id']} {d['title'][:18]}", callback_data=f"chi_{d['_id']}") for d in chunk]
    rows = [opens[i:i + 2] for i in range(0, len(opens), 2)]
    markup = InlineKeyboardMarkup(rows + [nav, [InlineKeyboardButton("+ Add Manhwa", callback_data="adds_home"),
                                               InlineKeyboardButton("◂ Back", callback_data="target_channel")]])
    return head + "".join(lines), markup


@Bot.on_message(filters.command("ch_list") & filters.private & admin_only)
async def ch_list_cmd(client, message):
    arg = args_of(message).lower()
    status = arg if arg in ("active", "paused", "error") else None
    page = int(arg) if arg.isdigit() else 1
    text, markup = await build_list(page, status)
    await reply(message, text, reply_markup=markup)


@Bot.on_callback_query(filters.regex(r"^chl_(\d+)_(\w+)$") & admin_only)
async def ch_list_cb(client, query):
    page, tag = int(query.matches[0].group(1)), query.matches[0].group(2)
    text, markup = await build_list(page, None if tag == "all" else tag)
    await edit_any(query, text, reply_markup=markup)
    await query.answer()


# ----------------------------------------------------------------- /ch_info ---
def batch_line(doc) -> str:
    mode = doc.get("mode", "latest")
    if doc.get("state") == "batch":
        total = int(doc.get("batch_total", 0))
        left = len([i for i in doc.get("batch_items", []) if i["key"] not in set(doc.get("posted", []))])
        return f"❖ Mode: <b>batch</b> - uploading backlog {total - left}/{total}\n"
    return f"❖ Mode: <b>{esc(mode)}</b> - watching for new chapters\n"


async def info_text(doc) -> str:
    fails = await chpoller.list_failures(doc["_id"])
    pending = sum(1 for t in queue.auto_pending() if t.map_id == doc["_id"])
    running = sum(1 for t in queue.auto_ongoing() if t.map_id == doc["_id"])
    text = (
        f"{status_icon(doc)} <b>#{doc['_id']} {esc(doc['title'])}</b>\n\n"
        f"◍ <code>{esc(doc['site'])}</code>  {esc(doc['series_url'])}\n"
        f"➥ {esc(doc['channel_title'])} (<code>{doc['channel_id']}</code>)\n"
        f"{batch_line(doc)}"
        f"❖ Last posted: <b>{esc(doc.get('last_chapter') or '-')}</b> · posted by bot: {doc.get('posted_count', 0)}\n"
        f"◔ Checked {ago(doc.get('last_checked'))} · next in "
        f"{max(0, int(doc.get('next_check', 0) - time.time())) // 60} min\n"
        f"⧖ In queue: {pending} waiting, {running} running\n"
        f"⌘ Join link: {esc(doc.get('invite_link') or 'none')}\n"
    )
    if doc.get("last_error"):
        text += f"▲ Last error: <code>{esc(doc['last_error'])}</code>\n"
    if fails:
        text += "✗ Failed: " + ", ".join(f"{esc(f['key'])} ({f['attempts']}x)" for f in fails[:10]) + "\n"
    return text


def info_markup(doc):
    pause = ("▸ Resume", f"chr_{doc['_id']}") if doc.get("status") != "active" else ("‖ Pause", f"chp_{doc['_id']}")
    check = "▸ Continue batch" if doc.get("state") == "batch" else "⟳ Check now"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(pause[0], callback_data=pause[1]),
         InlineKeyboardButton(check, callback_data=f"chc_{doc['_id']}")],
        [InlineKeyboardButton("⟳ Retry failed", callback_data=f"chf_{doc['_id']}"),
         InlineKeyboardButton("» Skip failed", callback_data=f"chs_{doc['_id']}")],
        [InlineKeyboardButton("■ Stop batch (new only)" if doc.get("state") == "batch" else "❖ Upload all missing (batch)",
                              callback_data=f"chbs_{doc['_id']}" if doc.get("state") == "batch" else f"chbb_{doc['_id']}")],
        [InlineKeyboardButton("✎ Rename", callback_data=f"chnm_{doc['_id']}"),
         InlineKeyboardButton("➜ Change channel", callback_data=f"chcc_{doc['_id']}")],
        [InlineKeyboardButton("✕ Remove", callback_data=f"chrm_{doc['_id']}"),
         InlineKeyboardButton("◂ List", callback_data="chl_1_all")],
    ])


@Bot.on_message(filters.command("ch_info") & filters.private & admin_only)
async def ch_info_cmd(client, message):
    doc = await pick_one(message, args_of(message))
    if doc:
        await reply(message, await info_text(doc), reply_markup=info_markup(doc))


# ------------------------------------------------- pause / resume / remove ---
@Bot.on_message(filters.command(["ch_pause", "ch_resume"]) & filters.private & admin_only)
async def ch_pause_resume_cmd(client, message):
    resume = message.command[0].lower() == "ch_resume"
    status = chmap.STATUS_ACTIVE if resume else chmap.STATUS_PAUSED
    query = args_of(message)
    if query.lower() == "all":
        docs = await chmap.list_maps()
        for d in docs:
            await chservice.set_status(d["_id"], status)
        return await reply(message, f"{'▸ Resumed' if resume else '‖ Paused'} {len(docs)} mapping(s).")
    doc = await pick_one(message, query)
    if doc:
        await chservice.set_status(doc["_id"], status)
        await reply(message, f"{'▸ Resumed' if resume else '‖ Paused'} <b>{esc(doc['title'])}</b> (#{doc['_id']}).")


@Bot.on_callback_query(filters.regex(r"^ch([pr])_(\d+)$") & admin_only)
async def ch_pause_cb(client, query):
    resume = query.matches[0].group(1) == "r"
    map_id = int(query.matches[0].group(2))
    await chservice.set_status(map_id, chmap.STATUS_ACTIVE if resume else chmap.STATUS_PAUSED)
    doc = await chmap.get_map(map_id)
    if doc:
        await edit_any(query, await info_text(doc), reply_markup=info_markup(doc))
    await query.answer("Resumed" if resume else "Paused")


@Bot.on_message(filters.command("ch_remove") & filters.private & admin_only)
async def ch_remove_cmd(client, message):
    doc = await pick_one(message, args_of(message))
    if doc:
        await reply(message, _remove_text(doc), reply_markup=_remove_markup(doc))


def _remove_text(doc):
    return (f"✕ Remove <b>#{doc['_id']} {esc(doc['title'])}</b> → {esc(doc['channel_title'])}?\n"
            "Posted chapters stay in the channel; auto-posting stops.")


def _remove_markup(doc):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✓ Yes, remove", callback_data=f"chry_{doc['_id']}"),
        InlineKeyboardButton("✕ No", callback_data="kclose"),
    ]])


@Bot.on_callback_query(filters.regex(r"^chrm_(\d+)$") & admin_only)
async def ch_remove_ask_cb(client, query):
    doc = await chmap.get_map(int(query.matches[0].group(1)))
    if not doc:
        return await query.answer("Already removed", show_alert=True)
    await edit_any(query, _remove_text(doc), reply_markup=_remove_markup(doc))
    await query.answer()


@Bot.on_callback_query(filters.regex(r"^chry_(\d+)$") & admin_only)
async def ch_remove_yes_cb(client, query):
    map_id = int(query.matches[0].group(1))
    removed = await chservice.remove_mapping(map_id)
    await edit_any(query, "✕ Removed." if removed else "Already removed.")
    await query.answer()


# ---------------------------------------------------------------- /ch_check ---
@Bot.on_message(filters.command("ch_check") & filters.private & admin_only)
async def ch_check_cmd(client, message):
    query = args_of(message)
    if query:
        doc = await pick_one(message, query)
        if not doc:
            return
        sts = await reply(message, f"<i>Checking {esc(doc['title'])}...</i>")
        res = await chpoller.check_map(doc, force=True)
        return await igrone_error(sts.edit)(_check_text(doc, res))

    docs = await chmap.list_maps(status=chmap.STATUS_ACTIVE)
    sts = await reply(message, f"<i>Checking {len(docs)} mapping(s) in the background...</i>")
    stats = await chpoller.poll_once(docs)
    await igrone_error(sts.edit)(
        f"⟳ Checked {stats['checked']} · queued {stats['queued']} chapter(s) · errors {stats['errors']} · "
        f"skipped {stats['skipped']} (site down)\nWatch progress with /queue")


def _check_text(doc, res):
    if res.get("skipped"):
        return f"» {esc(res['skipped'])}"
    if res.get("error"):
        return f"✗ <b>{esc(doc['title'])}</b>: <code>{esc(res['error'])}</code>"
    return f"✓ <b>{esc(doc['title'])}</b>: {res['queued']} new chapter(s) queued."


@Bot.on_callback_query(filters.regex(r"^chc_(\d+)$") & admin_only)
async def ch_check_cb(client, query):
    doc = await chmap.get_map(int(query.matches[0].group(1)))
    if not doc:
        return await query.answer("Mapping not found", show_alert=True)
    await query.answer("Checking...")
    res = await chpoller.check_map(doc, force=True)
    await igrone_error(query.message.reply_text)(_check_text(doc, res))


# -------------------------------------------------------------- /ch_backfill ---
@Bot.on_message(filters.command("ch_backfill") & filters.private & admin_only)
async def ch_backfill_cmd(client, message):
    parts = args_of(message).split()
    if len(parts) != 3:
        return await reply(message, "Usage: <code>/ch_backfill &lt;id&gt; &lt;from&gt; &lt;to&gt;</code>  e.g. <code>/ch_backfill 17 100 105</code>")
    try:
        low, high = float(parts[1]), float(parts[2])
    except ValueError:
        return await reply(message, "From/to must be chapter numbers")
    doc = await pick_one(message, parts[0])
    if not doc:
        return
    sts = await reply(message, "<i>Fetching chapters...</i>")
    try:
        res = await chservice.backfill(doc, low, high)
    except MapError as err:
        return await igrone_error(sts.edit)(f"✗ {esc(err)}")
    except Exception as err:
        return await igrone_error(sts.edit)(f"✗ <code>{esc(type(err).__name__)}: {esc(str(err)[:150])}</code>")
    await igrone_error(sts.edit)(f"⧖ {res['queued']} of {res['found']} chapter(s) queued for {esc(doc['title'])}. See /queue")


# ---------------------------------------------- failed / retry / skip / edit ---
@Bot.on_message(filters.command("ch_failed") & filters.private & admin_only)
async def ch_failed_cmd(client, message):
    query = args_of(message)
    map_id = None
    if query:
        doc = await pick_one(message, query)
        if not doc:
            return
        map_id = doc["_id"]
    fails = await chpoller.list_failures(map_id)
    if not fails:
        return await reply(message, "✓ No failed chapters.")
    lines = [f"✗ <b>{len(fails)} failed chapter(s)</b>"]
    for f in fails[:25]:
        lines.append(f"\n<code>#{f['map_id']}</code> ch <b>{esc(f['key'])}</b> · {f['attempts']}x · {esc(f.get('error', ''))[:100]}")
    lines.append("\n\n/ch_retry &lt;id&gt; to try again · /ch_skip &lt;id&gt; &lt;chapter&gt; to skip one")
    await reply(message, "".join(lines))


@Bot.on_message(filters.command("ch_retry") & filters.private & admin_only)
async def ch_retry_cmd(client, message):
    query = args_of(message)
    map_id = None
    if query:
        doc = await pick_one(message, query)
        if not doc:
            return
        map_id = doc["_id"]
    count = await chpoller.reset_failures(map_id)
    await chpoller_wake(map_id)
    await reply(message, f"⟳ Cleared {count} failed chapter(s); they will be retried on the next check (or /ch_check).")


async def chpoller_wake(map_id):
    """Make the mapping(s) due right now."""
    flt = {"_id": int(map_id)} if map_id is not None else {"status": chmap.STATUS_ACTIVE}
    await chmap._col().update_many(flt, {"$set": {"next_check": 0}})


@Bot.on_message(filters.command("ch_skip") & filters.private & admin_only)
async def ch_skip_cmd(client, message):
    parts = args_of(message).split()
    if len(parts) != 2:
        return await reply(message, "Usage: <code>/ch_skip &lt;id&gt; &lt;chapter number&gt;</code>")
    doc = await pick_one(message, parts[0])
    if not doc:
        return
    key = chmap.chapter_key(f"Chapter {parts[1]}")
    if key is None:
        return await reply(message, "That is not a chapter number")
    await chmap.record_posted(doc["_id"], key)
    await chpoller.clear_failure(doc["_id"], key)
    await chpoller_wake(doc["_id"])
    await reply(message, f"» Chapter {esc(key)} of <b>{esc(doc['title'])}</b> marked as done - it will not be posted.")


@Bot.on_message(filters.command("ch_edit") & filters.private & admin_only)
async def ch_edit_cmd(client, message):
    parts = args_of(message).split(maxsplit=2)
    if len(parts) != 3 or parts[1] not in ("url", "channel", "name"):
        return await reply(message, "Usage: <code>/ch_edit &lt;id&gt; url|channel|name &lt;new value&gt;</code>")
    doc = await pick_one(message, parts[0])
    if not doc:
        return
    field, value = parts[1], parts[2].strip()
    try:
        if field == "name":
            await chmap.update_map(doc["_id"], title=value)
        elif field == "url":
            from TG.storage import web_data
            web = chmap.detect_site(value, web_data)
            if web is None:
                raise MapError("Unsupported site. Supported: " + chmap.allowed_site_names(web_data))
            await chmap.update_map(doc["_id"], series_url=value, site=web.sf, last_error=None, fail_count=0, next_check=0)
        else:
            if not value.lstrip("-").isdigit() or not chmap._CHANNEL_RE.match(value):
                raise MapError("Channel id must look like -1001234567890")
            channel_id = int(value)
            title, can_invite = await chservice.check_channel(channel_id)
            invite = await chservice.make_invite_link(channel_id) if can_invite else None
            await chmap.update_map(doc["_id"], channel_id=channel_id, channel_title=title, invite_link=invite)
    except MapError as err:
        return await reply(message, f"✗ {esc(err)}")
    await reply(message, f"✎ Updated {field} of <b>#{doc['_id']}</b>.")


# ------------------------------------------------------ import / export ---
@Bot.on_message(filters.command("ch_import") & filters.private & admin_only)
async def ch_import_cmd(client, message):
    text = ""
    src = message.reply_to_message
    if src and src.document:
        buf = await client.download_media(src, in_memory=True)
        text = bytes(buf.getbuffer()).decode("utf-8", "ignore") if buf else ""
    elif src and src.text:
        text = src.text
    else:
        text = (message.text or "").split("\n", 1)[1] if "\n" in (message.text or "") else ""

    if not text.strip():
        return await reply(message, (
            "Send the list as a .txt file and <b>reply to it</b> with /ch_import, or paste lines under the command.\n"
            "One per line: <code>&lt;manga name&gt; &lt;manga url&gt; &lt;channel id&gt;</code>\n"
            "Lines starting with # are ignored. /ch_export makes a file in this format."))

    entries, bad = chmap.parse_import_lines(text)
    if not entries:
        return await reply(message, "No valid lines found.\n" + "\n".join(f"line {n}: {esc(r)}" for n, _, r in bad[:10]))

    sts = await reply(message, f"<i>Importing {len(entries)} mapping(s)...</i>")
    last = {"t": 0.0}

    async def progress(done, total):
        if time.time() - last["t"] > 4 or done == total:
            last["t"] = time.time()
            from Tools.progress import bar
            await igrone_error(sts.edit)(f"<i>Importing...</i>\n<code>{bar(done * 100 / total)} {done}/{total}</code>")

    result = await chservice.import_many(entries, message.from_user.id, on_progress=progress)
    out = [f"✓ Added {len(result['ok'])} · ✗ failed {len(result['failed']) + len(bad)}"]
    for n, line, reason in bad[:10]:
        out.append(f"line {n}: {esc(reason)}")
    for line, reason in result["failed"][:15]:
        out.append(f"• {esc(line)} - {esc(reason)}")
    await igrone_error(sts.edit)("\n".join(out)[:4000])


@Bot.on_message(filters.command("ch_export") & filters.private & admin_only)
async def ch_export_cmd(client, message):
    docs = await chmap.list_maps()
    if not docs:
        return await reply(message, "Nothing to export.")
    data = io.BytesIO(chservice.export_lines(docs).encode())
    data.name = "channel_maps.txt"
    await retry_on_flood(message.reply_document)(data, caption=f"{len(docs)} mapping(s). Re-import with /ch_import.")


# --------------------------------------------------------- stats / sites ---
@Bot.on_message(filters.command("ch_stats") & filters.private & admin_only)
async def ch_stats_cmd(client, message):
    counts = await chmap.count_maps()
    fails = await chpoller.list_failures()
    docs = await chmap.list_maps()
    posted = sum(d.get("posted_count", 0) for d in docs)
    await reply(message, (
        "▤ <b>Auto-post stats</b>\n\n"
        f"Mappings: {sum(counts.values())}  (● {counts.get('active', 0)} · ‖ {counts.get('paused', 0)} · ◉ {counts.get('error', 0)})\n"
        f"Chapters posted by the bot: {posted}\n"
        f"Queue: {len(queue.auto_pending())} waiting · {queue.auto_running()}/{Vars.AUTO_MAX_PARALLEL} running\n"
        f"Failed chapters: {len(fails)}\n"
        f"Poll every {Vars.POLL_MINUTES} min"))


@Bot.on_message(filters.command("ch_sites") & filters.private & admin_only)
async def ch_sites_cmd(client, message):
    from TG.storage import web_data
    lines = ["◍ <b>Sites</b>\n"]
    counts = {}
    for d in await chmap.list_maps():
        counts[d["site"]] = counts.get(d["site"], 0) + 1
    for web in web_data.values():
        if web.sf not in Vars.MAP_SITES:
            continue
        gate = chpoller.gate_for(web.sf)
        state = "◉ down" if gate.is_down else ("◎ errors" if gate.fail_streak else "● ok")
        lines.append(f"{state} <b>{esc(web.url)}</b> · {counts.get(web.sf, 0)} mapped · last ok {ago(gate.last_ok)}"
                     + (f"\n   <code>{esc(gate.last_error)[:90]}</code>" if gate.last_error and gate.fail_streak else ""))
    await reply(message, "\n".join(lines))

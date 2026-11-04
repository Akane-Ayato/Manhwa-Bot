"""Gate (ban + maintenance), /stop, /admin.   Runs before every other handler (group -3)."""
import asyncio
import os

from pyrogram import filters

from bot import Bot, Vars, logger
from Tools import control
from Tools.base import queue, retry_on_flood, igrone_error


def _owner(_, __, update):
    user = getattr(update, "from_user", None)
    return bool(user and control.is_owner(user.id))


def _admin(_, __, update):
    user = getattr(update, "from_user", None)
    return bool(user and user.id in Vars.ADMINS)


owner_only = filters.create(_owner)
admin_only = filters.create(_admin)

BANNED_TEXT = "<b>⊘ You are banned from using this bot.</b>"
MAINT_TEXT = "<b>✦ The bot is in maintenance mode.</b>\nPlease try again later."


async def _stop_listening_active(message) -> bool:
    try:
        from TG.target_ import Listeing_cache
        return str(message.from_user.id) in Listeing_cache
    except Exception:
        return False


def _blocked(user_id) -> str:
    """Reason text if this user must be stopped, else ''."""
    if control.is_owner(user_id):
        return ""
    if control.is_banned(user_id):
        return BANNED_TEXT
    if control.maintenance():
        return MAINT_TEXT
    return ""


@Bot.on_message(filters.private, group=-3)
async def gate_message(client, message):
    if not message.from_user:
        return
    text = _blocked(message.from_user.id)
    if text:
        await igrone_error(message.reply_text)(text)
        message.stop_propagation()


@Bot.on_callback_query(group=-3)
async def gate_callback(client, query):
    text = _blocked(query.from_user.id)
    if text:
        await igrone_error(query.answer)(text.replace("<b>", "").replace("</b>", "")[:190], show_alert=True)
        query.stop_propagation()


# -------------------------------------------------------------------- /stop ---
@Bot.on_message(filters.command("stop") & filters.private & owner_only, group=-3)
async def stop_cmd(client, message):
    if await _stop_listening_active(message):
        return                      # owner is inside a target-channel dialog: /stop keeps its old meaning
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg == "off":
        await control.set_maintenance(False)
        await message.reply_text("● Maintenance mode <b>OFF</b> - everyone can use the bot again.")
    elif arg == "kill":
        await control.set_maintenance(True)
        await message.reply_text("✗ Shutting down completely. Start the bot again from your host.")
        await asyncio.sleep(1)
        os._exit(0)
    else:
        await control.set_maintenance(True)
        cancelled = 0
        if arg == "now":
            users = {int(t.user_id) for t, _ in queue.storage_data.values() if getattr(t, "kind", "user") == "user"}
            users |= {int(t.user_id) for t in queue.ongoing_tasks.values() if getattr(t, "kind", "user") == "user"}
            for uid in users:
                p, r = await queue.cancel_user(uid)
                cancelled += p + r
        await message.reply_text(
            "✦ Maintenance mode <b>ON</b>. Nobody except you can use the bot; the state is saved across restarts.\n"
            + (f"Cancelled {cancelled} user task(s).\n" if arg == "now" else "Tasks already running finish normally (/stop now cancels them).\n")
            + "Channel auto-posting keeps running.\n\n/stop off - open again · /stop kill - exit the process")
    message.stop_propagation()


# ------------------------------------------------------------------- /admin ---
ADMIN_HELP = (
    "<b>♕ Admin panel</b>\n\n"
    "<code>/admin list</code> - admins\n"
    "<code>/admin add &lt;id&gt;</code> · <code>/admin remove &lt;id&gt;</code> (owner)\n"
    "<code>/admin ban &lt;id&gt; [reason]</code> · <code>/admin unban &lt;id&gt;</code> · <code>/admin bans</code>"
)


@Bot.on_message(filters.command("admin") & filters.private & admin_only)
async def admin_cmd(client, message):
    parts = (message.text or "").split(maxsplit=3)
    sub = parts[1].lower() if len(parts) > 1 else ""
    if not sub:
        return await message.reply_text(admin_panel_text(), reply_markup=admin_panel_markup(control.is_owner(message.from_user.id)))
    arg = parts[2] if len(parts) > 2 else ""
    reason = parts[3] if len(parts) > 3 else ""
    owner = control.is_owner(message.from_user.id)

    if sub == "list":
        lines = [f"<code>{a}</code>{' ♕' if control.is_owner(a) else ''}" for a in Vars.ADMINS]
        return await message.reply_text("<b>Admins:</b>\n" + "\n".join(lines))
    if sub == "bans":
        rows = await control.list_banned()
        return await message.reply_text("<b>Banned:</b>\n" + ("\n".join(
            f"<code>{d['_id']}</code> {d.get('reason', '')}" for d in rows) or "nobody"))
    if sub in ("add", "remove", "ban", "unban"):
        if not arg.lstrip("-").isdigit():
            return await message.reply_text("Give a numeric user id.\n\n" + ADMIN_HELP)
        uid = int(arg)
        if sub in ("add", "remove") and not owner:
            return await message.reply_text("Only the owner can add or remove admins.")
        result = {"add": control.add_admin, "remove": control.remove_admin, "unban": control.unban}.get(sub)
        out = await (result(uid) if result else control.ban(uid, reason))
        return await message.reply_text(f"<code>{uid}</code>: {out}")
    await message.reply_text(ADMIN_HELP)


def admin_panel_text() -> str:
    return ("<b>Admin panel</b>\n\nTap a button. Typed forms: /admin add|remove &lt;id&gt; (owner), "
            "/admin ban &lt;id&gt; [reason], /admin unban &lt;id&gt;.\n"
            f"Mode now: <b>{'maintenance' if control.maintenance() else 'normal'}</b>")


def admin_panel_markup(owner: bool):
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton("Admins", callback_data="adm_list"), InlineKeyboardButton("Banned", callback_data="adm_bans")],
            [InlineKeyboardButton("Series (manage)", callback_data="chl_1_all"), InlineKeyboardButton("Help", callback_data="gd_adm")]]
    if owner:
        rows.append([InlineKeyboardButton("Maintenance: turn " + ("OFF" if control.maintenance() else "ON"), callback_data="adm_maint")])
    rows.append([InlineKeyboardButton("Close", callback_data="kclose")])
    return InlineKeyboardMarkup(rows)


@Bot.on_callback_query(filters.regex(r"^adm_(list|bans|maint)$") & admin_only)
async def admin_cb(client, query):
    what = query.matches[0].group(1)
    owner = control.is_owner(query.from_user.id)
    if what == "maint":
        if not owner:
            return await query.answer("Owner only", show_alert=True)
        await control.set_maintenance(not control.maintenance())
        await query.answer("Maintenance " + ("ON" if control.maintenance() else "OFF"))
    elif what == "list":
        text = "<b>Admins</b>\n" + "\n".join(f"<code>{a}</code>{' (owner)' if control.is_owner(a) else ''}" for a in Vars.ADMINS)
        await igrone_error(query.message.edit_text)(text, reply_markup=admin_panel_markup(owner))
        return await query.answer()
    elif what == "bans":
        rows = await control.list_banned()
        text = "<b>Banned</b>\n" + ("\n".join(f"<code>{d['_id']}</code> {d.get('reason', '')}" for d in rows) or "nobody")
        await igrone_error(query.message.edit_text)(text, reply_markup=admin_panel_markup(owner))
        return await query.answer()
    await igrone_error(query.message.edit_text)(admin_panel_text(), reply_markup=admin_panel_markup(owner))

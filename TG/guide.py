"""Interactive help center: /help (and the Help button) -> category pages, /help <command> -> one card.

Every command of the bot is described here with what it does, how to type it and an example.
Pages are filtered by role (user / admin / owner)."""
import random

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from bot import Bot, Vars
from Tools.base import igrone_error, retry_on_flood
from Tools import control

# name -> (role, usage, what it does)      role: user | admin | owner
COMMANDS = {
    "start": ("user", "/start", "Open the main menu."),
    "help": ("user", "/help  or  /help add", "This guide. Add a command name to see only that command."),
    "settings": ("user", "/settings",
                 "Your personal panel: banner, caption, file name, file type, compress, thumbnail, merge size, "
                 "password, regex, dump channel, upload channels and the Auto Post switch. "
                 "Open a button, read the hint, send the value."),
    "queue": ("user", "/queue", "Live progress bars of everything that is running, and how many are waiting."),
    "clean": ("user", "/clean", "Stop YOUR running task and remove your waiting ones. Only works in the bot's DM; "
                                "channel auto-posts are not touched (admins: /clean all)."),
    "my_plan": ("user", "/my_plan", "See your plan (free or premium) and when it ends."),
    "search": ("user", "just send a name", "Type any manga / manhwa name, pick the language, then the site, "
                                          "then subscribe or choose chapters. A chapter link also works."),
    "test_settings": ("user", "/test_settings  (or Settings > Test Settings)",
                      "Runs the REAL upload pipeline on 4 sample pages with YOUR settings, sends the result to you "
                      "and lists what was applied: file name, caption, banners, thumbnail, password, before/after "
                      "post, stickers, dump channel, update post preview, channel rights."),
    "quickstart": ("admin", "/help quickstart",
                   "First run in 6 steps: 1) /settings > set file name, caption, banners and your Update Channel. "
                   "2) /settings > Test Settings and read the report. 3) Make the bot ADMIN of your upload channel "
                   "(post + invite rights) and of the update channel. 4) Settings > Auto Upload Channels > Map Manhwa: "
                   "pick the source site, paste the series link, pick the channel, choose Batch (all chapters, then "
                   "new ones) or Latest (new chapters only). 5) Watch it with /queue or open the series card. "
                   "6) If a chapter fails, open the card and press Retry or Skip. Sources: Weeb Central, Mgeko, "
                   "Manga18fx, Manhwa18, Manhuaplus, Asura Scans."),
    "automap": ("admin", "Settings > Auto Upload Channels > Map Manhwa",
                "The whole series -> channel setup lives there: add a manhwa (3 button steps), open it to pause, "
                "check, switch batch/latest, retry/skip failed chapters, rename, change channel or remove it. "
                "Every Settings value applies to these uploads and to the update-channel post."),
    "add": ("admin", "/add <channel id> <source> <series url> <batch|latest> [title]",
            "Connect a series to a channel. Send /add alone for a guided, button-based setup. "
            "batch = upload every existing chapter in order, then new ones.  latest = only new chapters."),
    "manage": ("admin", "/manage  or  /manage <id|name>",
               "List of every connection. Open one to pause, resume, check now, retry/skip a failed chapter or remove it."),
    "stats": ("admin", "/stats", "Server load plus users, premium, banned, series, queues and site health."),
    "broadcast": ("admin", "/broadcast  (reply to a message)", "Send a message to all users. /pbroadcast also pins it."),
    "admin": ("admin", "/admin", "Panel for admins and bans. Typed form: /admin add|remove <id> (owner), "
                                 "/admin ban <id> [reason], /admin unban <id>, /admin list, /admin bans."),
    "premium": ("admin", "/premium  |  /premium add <id> <days>  |  /premium remove <id>",
                "List premium users with days left, give or take premium."),
    "update": ("admin", "/update", "Pull the newest code from your GitHub repo/branch and restart."),
    "restart": ("admin", "/restart", "Restart the bot process."),
    "stop": ("owner", "/stop | /stop now | /stop off | /stop kill",
             "Maintenance mode: nobody but you gets answers. now = also cancel running tasks, "
             "off = open again, kill = shut the process down."),
}

PAGES = {
    "dl": ("user", "Download & subscribe", ["search", "my_plan", "queue", "clean"]),
    "set": ("user", "Settings", ["settings", "test_settings", "start", "help"]),
    "auto": ("admin", "Channel auto-post", ["quickstart", "automap", "add", "manage", "stats"]),
    "adm": ("admin", "Admin tools", ["admin", "premium", "broadcast", "update", "restart"]),
    "own": ("owner", "Owner", ["stop"]),
}

ROLE_ORDER = {"user": 0, "admin": 1, "owner": 2}


def role_of(user_id: int) -> str:
    if control.is_owner(user_id):
        return "owner"
    return "admin" if user_id in Vars.ADMINS else "user"


def allowed(role: str, need: str) -> bool:
    return ROLE_ORDER[role] >= ROLE_ORDER[need]


def card(name: str) -> str:
    role, usage, what = COMMANDS[name]
    tag = {"user": "everyone", "admin": "admins", "owner": "owner only"}[role]
    return f"<b>/{name}</b>  ({tag})\n<b>Type:</b> <code>{usage}</code>\n{what}"


def home_markup(role: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, (need, title, _) in PAGES.items():
        if allowed(role, need):
            row.append(InlineKeyboardButton(title, callback_data=f"gd_{key}"))
            if len(row) == 2:
                rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Settings", callback_data="mus"), InlineKeyboardButton("Queue", callback_data="refresh_queue")])
    rows.append([InlineKeyboardButton("Close", callback_data="kclose")])
    return InlineKeyboardMarkup(rows)


def home_text(role: str) -> str:
    return ("<b>Help center</b>\n\n"
            "Pick a topic below. Every page explains what a command does, how to type it and gives an example.\n\n"
            "<b>Quick start:</b> send a manga name -> choose language -> choose site -> choose chapters.\n"
            "Set your look first with /settings.\n"
            f"<i>You are: {role}. Tip: /help add shows one command only.</i>")


def page(key: str, role: str):
    need, title, names = PAGES[key]
    names = [n for n in names if allowed(role, COMMANDS[n][0])]
    text = f"<b>{title}</b>\n\n" + "\n\n".join(card(n) for n in names)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="gd_home"),
                                    InlineKeyboardButton("Close", callback_data="kclose")]])
    return text, markup


async def _show(target, text, markup, edit):
    """edit=False: `target` is a Message -> new photo+caption (or text if long).
    edit=True: `target` is a CallbackQuery -> edit its message in place (text or caption)."""
    if not edit:
        if Vars.PICS and len(text) < 1000:
            return await retry_on_flood(target.reply_photo)(random.choice(Vars.PICS), caption=text, reply_markup=markup)
        return await retry_on_flood(target.reply_text)(text, reply_markup=markup)

    message = target.message
    if getattr(message, "photo", None):
        if len(text) < 1000:
            return await retry_on_flood(target.edit_message_caption)(text, reply_markup=markup)
        await igrone_error(message.delete)()           # caption limit: continue as a plain text message
        return await retry_on_flood(message.reply_text)(text, reply_markup=markup)
    return await retry_on_flood(target.edit_message_text)(text, reply_markup=markup)


@Bot.on_message(filters.command("help"))
async def help_cmd(client, message):
    role = role_of(message.from_user.id)
    if len(message.command) > 1:
        name = message.command[1].lstrip("/").lower()
        if name in COMMANDS and allowed(role, COMMANDS[name][0]):
            return await retry_on_flood(message.reply_text)(
                card(name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("All commands", callback_data="gd_home")]]))
        return await retry_on_flood(message.reply_text)(
            f"No command called <code>{name}</code> for you. Open the /help center.")
    await _show(message, home_text(role), home_markup(role), edit=False)


@Bot.on_callback_query(filters.regex(r"^(help|gd_home)$"))
async def help_home_cb(client, query):
    role = role_of(query.from_user.id)
    await _show(query, home_text(role), home_markup(role), edit=True)
    await igrone_error(query.answer)()


@Bot.on_callback_query(filters.regex(r"^gd_(\w+)$"))
async def help_page_cb(client, query):
    key = query.matches[0].group(1)
    role = role_of(query.from_user.id)
    if key not in PAGES or not allowed(role, PAGES[key][0]):
        return await igrone_error(query.answer)("Not available for you", show_alert=True)
    text, markup = page(key, role)
    await _show(query, text, markup, edit=True)
    await igrone_error(query.answer)()

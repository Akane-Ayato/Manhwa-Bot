from Tools.base import igrone_error
from bot import Bot, Vars, logger
from pyrogram import filters
from TG.storage import retry_on_flood, queue
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
import random
import asyncio

from pyrogram.types import BotCommand

botcommands = {
  "start": "Start the bot",
  "help": "Get help about the bot",
  "queue": "To Check Queue List",
  "user_setting": "To Change User Settings",
  "search": "To Search For A Manga",
  "subscribes": "To Check Your Subscribed Manga",

  "ch_map": "Map a manhwa to a channel (admin)",
  "ch_list": "List all channel mappings (admin)",
  "ch_info": "Details of one mapping (admin)",
  "ch_pause": "Pause a mapping (admin)",
  "ch_resume": "Resume a mapping (admin)",
  "ch_remove": "Remove a mapping (admin)",
  "ch_check": "Check for new chapters now (admin)",
  "ch_failed": "List failed chapters (admin)",
  "ch_stats": "Auto-post statistics (admin)",

  "settings": "Banner, caption, filename, dump channel, thumbnail, auto upload",
  "clean": "Cancel your running and waiting tasks",
  "add": "Connect a series to a channel (admin)",
  "manage": "Manage connected channels (admin)",
  "admin": "Admins and bans (owner)",
  "stop": "Maintenance mode (owner)",
  "shell": "To Run Shell Commands",
  "stats": "To Get OS Stats Of Bot",
  "update": "To Update The Bot",
  "restart": "To Restart The Bot",
  "b": "To Broadcast Message To All Users",
  "pb": "To Broadcast Message To All Users With Pinning",
  "fd": "To Forward Message To All Users",
  "pfd": "To Forward Message To All Users With Pinning",
  "add_admin": "To Add New Admin",

}
@Bot.on_message(filters.command("cmds"))
async def set_bot_commands(client, message):
    if not message.from_user or message.from_user.id not in Vars.ADMINS:
        return  # changes the command menu for every user - admins only
    bot_commands = [BotCommand(command, description) for command, description in botcommands.items()]
    await client.set_bot_commands(bot_commands)
    #await retry_on_flood(message.reply_text)("<i> <b> Bot commands updated successfully! </b> </i>")


def get_queue_markup(user_error=None):
    button = [
        [
            InlineKeyboardButton("⌜ 𝙲𝚕𝚎𝚊𝚗 𝚀𝚞𝚎𝚞𝚎 ⌟", callback_data="clean_queue"),
            InlineKeyboardButton("⌜ 𝚂𝚞𝚋𝚜𝚌𝚛𝚒𝚋𝚎 ⌟", callback_data="isubs")
        ],
        [
            InlineKeyboardButton("▏ 𝗖𝗟𝗢𝗦𝗘 ▕", callback_data="kclose"),
            InlineKeyboardButton(" 𝗥𝗘𝗙𝗥𝗘𝗦𝗛 ⟳ ", callback_data="refresh_queue")
        ]
    ]
    if user_error:
        button.append([InlineKeyboardButton("♕ 𝙾𝚠𝚗𝚎𝚛 ♕", url="https://t.me/Wizard_Bots")])
    elif Vars.OWNER:
        button.append([InlineKeyboardButton("♕ 𝙾𝚠𝚗𝚎𝚛 ♕", user_id=Vars.OWNER)])

    return InlineKeyboardMarkup(button)

def auto_queue_text(max_running: int = 8, max_waiting: int = 8) -> str:
    """Admin section: channel uploads (running with progress bars + the next waiting ones)."""
    running = queue.auto_ongoing()
    waiting = queue.auto_pending()
    txt = (f"\n\n<b>➥ Channel auto-posts</b>  ({len(running)}/{Vars.AUTO_MAX_PARALLEL} running · "
           f"{len(waiting)} waiting)\n")
    if not running and not waiting:
        return txt + "=> <i>Nothing running.</i>"
    if running:
        txt += "<blockquote expandable>"
        for task in running[:max_running]:
            txt += (f"<b>{task.orginal_manga_title}</b> - {task.episode_number}\n"
                    f"→ {task.target_title or task.chat_id}\n<code>{task.progress.line()}</code>\n\n")
        if len(running) > max_running:
            txt += f"... +{len(running) - max_running} more\n"
        txt += "</blockquote>"
    if waiting:
        txt += "<blockquote expandable>"
        for task in waiting[:max_waiting]:
            txt += f"⧖ {task.orginal_manga_title} - {task.episode_number} → {task.target_title or task.chat_id}\n"
        if len(waiting) > max_waiting:
            txt += f"... +{len(waiting) - max_waiting} more\n"
        txt += "</blockquote>"
    return txt


async def get_queue_text(user_id):
    try:
        total_tasks = queue.qsize()
        total_users = queue.get_count()
        ongoing_tasks = list(queue.ongoing_tasks.values())

        reply_txt = (
            f"<blockquote><b>✦ Queue Status (Total: {total_tasks} chapters & {total_users} Users)</b></blockquote>\n\n"
            "**♞ Your queue:**"
        )

        user_count = queue.get_count(user_id)

        if user_count != 0:
            reply_txt += f"""<blockquote expandable>=> <i>Total Chapters: {user_count}</i>\n"""

            # Check if user has ongoing task
            if user_id in queue.ongoing_tasks:
                task = queue.ongoing_tasks[user_id]
                reply_txt += f"=> <i>{task.manga_title} - {task.episode_number}</i>\n"
                reply_txt += f"=> <code>{task.progress.line()}</code>\n"
            else:
                # Get waiting tasks
                available_tasks = queue.get_available_tasks(user_id)
                if available_tasks:
                    task = available_tasks[0]
                    reply_txt += f"=> <i>{task.manga_title} - {task.episode_number}</i>\n"
                    reply_txt += "=> <i>Waiting...</i>\n"
                else:
                    reply_txt += "=> <i>In queue...</i>\n"
            reply_txt += "</blockquote>\n"
        else:
            reply_txt += "\n=> <i>No chapters in your queue.</i>\n"

        # Global processing section
        reply_txt += "\n**◈ Now Processing:**\n"
        if ongoing_tasks:
            reply_txt += "<blockquote expandable>"
            for i, data in enumerate([t for t in ongoing_tasks if t.kind != "auto"], 1):
                if user_id in Vars.ADMINS:
                    try:
                        who = (await Bot.get_users(int(data.user_id))).mention()
                    except Exception:
                        who = f"User[{data.user_id}]"
                else:
                    who = f"User ••{str(data.user_id)[-3:]}"          # other people's ids stay private
                reply_txt += (f"{i}. {who} - {data.manga_title} {data.episode_number}\n"
                              f"   <code>{data.progress.line()}</code>\n")
            reply_txt += "</blockquote>\n"
        else:
            reply_txt += "=> <i>No active processing tasks.</i>\n\n"

        reply_txt += "<b>=> <i>Other chapters are in the waiting line.</i></b>"
        if user_id in Vars.ADMINS:
            reply_txt += auto_queue_text()
        return reply_txt

    except Exception as e:
        logger.exception(f"Error generating queue text: {e}")
        return "✗ Error generating queue information."


@Bot.on_message(filters.command("queue"))
async def queue_msg_handler(client, message):
    if Vars.IS_PRIVATE and message.chat.id not in Vars.ADMINS:
        return await message.reply("<code>You cannot use this command.</code>")

    try:
        await retry_on_flood(message.reply_text)(
            await get_queue_text(message.from_user.id),
            quote=True,
            reply_markup=get_queue_markup()
        )
    except Exception:
        try:
            await retry_on_flood(message.reply_text)(
                await get_queue_text(message.from_user.id),
                quote=True,
                reply_markup=get_queue_markup(True)
            )
        except Exception as e:
            logger.error(f"Queue command error: {e}")
            await message.reply("✗ Failed to fetch queue information.")



async def _edit_queue_message(query, text, markup):
    """Edit the queue message whether it is plain text or a photo with a caption."""
    try:
        await retry_on_flood(query.edit_message_text)(text, reply_markup=markup)
    except Exception:
        await retry_on_flood(query.edit_message_caption)(text, reply_markup=markup)


@Bot.on_callback_query(filters.regex("^refresh_queue$"))
async def queue_refresh_handler(_, query):
    """Refresh queue information"""
    try:
        text = await get_queue_text(query.from_user.id)
        try:
            await _edit_queue_message(query, text, get_queue_markup())
        except Exception:
            await _edit_queue_message(query, text, get_queue_markup(True))

        await igrone_error(query.answer)("✓ Queue refreshed!")
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" in str(e).upper():
            return await igrone_error(query.answer)("Nothing changed yet")
        logger.error(f"Queue refresh error: {e}")
        await igrone_error(query.answer)("✗ Failed to refresh queue.", show_alert=True)


@Bot.on_callback_query(filters.regex("^clean_queue$"))
async def clean_queue_handler(_, query):
    """Clean user's queue"""
    try:
        user_id = query.from_user.id
        if queue.get_count(user_id):
            numb = await queue.delete_tasks(user_id)
            await retry_on_flood(query.answer)(f"✓ All your tasks deleted: {numb}")

            await asyncio.sleep(1)
            await _edit_queue_message(query, await get_queue_text(user_id), get_queue_markup(True))
        else:
            await retry_on_flood(query.answer)("ⓘ There are no pending tasks in your queue.")
    except Exception as e:
        logger.error(f"Clean queue error: {e}")
        await query.answer("✗ Failed to clean queue.", show_alert=True)

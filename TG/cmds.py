from pyrogram import filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from .storage import *
import pyrogram.errors

from bot import Bot, Vars, logger

import random
from Tools.db import database
from Tools.my_token import verify_token

import time

from asyncio import create_subprocess_exec
import os
from os import execl
from sys import executable

import shutil, psutil, time, os, platform
import asyncio

from io import BytesIO
from copy import deepcopy
import subprocess


HELP_MSG = """
<blockquote>Tᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴀ ᴍᴀɴɢᴀ ᴊᴜsᴛ ᴛʏᴘᴇ ᴛʜᴇ ɴᴀᴍᴇ ᴏғ ᴛʜᴇ ᴍᴀɴɢᴀ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴋᴇᴇᴘ ᴜᴘ ᴛᴏ ᴅᴀᴛᴇ..</blockquote>

For example: `One Piece`

<blockquote>Tʜᴇɴ ʏᴏᴜ ᴡɪʟʟ ʜᴀᴠᴇ ᴛᴏ ᴄʜᴏᴏsᴇ ᴛʜᴇ ʟᴀɴɢᴜᴀɢᴇ ᴏғ ᴛʜᴇ ᴍᴀɴɢᴀ. Dᴇᴘᴇɴᴅɪɴɢ ᴏɴ ᴛʜɪs ʟᴀɴɢᴜᴀɢᴇ, ʏᴏᴜ ᴡɪʟʟ ʙᴇ ᴀʙʟᴇ ᴛᴏ ᴄʜᴏᴏsᴇ ᴛʜᴇ ᴡᴇʙsɪᴛᴇ ᴡʜᴇʀᴇ ʏᴏᴜ ᴄᴏᴜʟᴅ ᴅᴏᴡɴʟᴏᴀᴅ ᴛʜᴇ ᴍᴀɴɢᴀ. Hᴇʀᴇ ʏᴏᴜ ᴡɪʟʟ ʜᴀᴠᴇ ᴛʜᴇ ᴏᴘᴛɪᴏɴ ᴛᴏ sᴜʙsᴄʀɪʙᴇ, ᴏʀ ᴛᴏ ᴄʜᴏᴏsᴇ ᴀ ᴄʜᴀᴘᴛᴇʀ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ. Tʜᴇ ᴄʜᴀᴘᴛᴇʀs ᴀʀᴇ sᴏʀᴛᴇᴅ ᴀᴄᴄᴏʀᴅɪɴɢ ᴛᴏ ᴛʜᴇ ᴡᴇʙsɪᴛᴇ..</blockquote>

<blockquote><b>Updates Channel : @Manga_Cruise</b></blockquote>
"""
start_text = """<b>◈ MANGA BOT ◈</b>

<blockquote><b>➤ Send a name</b> - search any manga / manhwa
➤ <b>Send a chapter link</b> - get it as a file
➤ <b>/settings</b> - banner, caption, file name, channels
➤ <b>/queue</b> - live progress of every task</blockquote>

<blockquote expandable>Auto upload: open /settings > Auto Upload Channels > Map Manhwa to connect a series to a channel. New chapters (or the whole backlog) are posted by themselves, with your settings, and announced in your update channel.</blockquote>

<i>Tap Help for every command with examples.</i>"""

Start_Button = [
  [
    InlineKeyboardButton(" ᴋ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ᴏ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ɴ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ɴ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ɪ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ᴄ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ʜ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ɪ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ᴡ ", callback_data="just_kidding"),
    InlineKeyboardButton(" ᴀ ", callback_data="just_kidding"),
  ],
  [
    InlineKeyboardButton(" 𝚂𝚎𝚝𝚝𝚒𝚗𝚐𝚜 ", callback_data="mus"),
    InlineKeyboardButton(" 𝚀𝚞𝚎𝚞𝚎 ", callback_data="refresh_queue")
  ],
  [
    InlineKeyboardButton(" 𝚂𝚞𝚋𝚜𝚌𝚛𝚒𝚋𝚎 ", callback_data="isubs"),
    InlineKeyboardButton(" 𝙷𝚎𝚕𝚙 ", callback_data="help")
  ], 
  [
    InlineKeyboardButton(" ᴄ ", callback_data="kclose"),
    InlineKeyboardButton(" ʟ ", callback_data="kclose"),
    InlineKeyboardButton(" ᴏ ", callback_data="kclose"),
    InlineKeyboardButton(" s ", callback_data="kclose"),
    InlineKeyboardButton(" ᴇ ", callback_data="kclose")
  ]
]
help_button = deepcopy(Start_Button)
help_button[2][-1] = InlineKeyboardButton(" ʜᴏᴍᴇ ", callback_data="home")


@Bot.on_callback_query(filters.regex("^home$"))
@Bot.on_message(filters.command("start"))
async def start(client, message):
  try:
    if Vars.IS_PRIVATE and message.chat.id not in Vars.ADMINS:
        return await message.reply("<code>hii </code>")

    await database.ensure_user(message.from_user.id)
  except Exception:
    pass 

  try:
    if len(message.command) > 1:
      if message.command[1] != "start":
        user_id = message.from_user.id
        token = message.command[1]
        sts = await retry_on_flood(message.reply)("<i>ㅤProcessing.....</i>")
        return await verify_token(sts, user_id, token)

  except Exception:
    pass

  photo = random.choice(Vars.PICS)
  ping = time.strftime("%H𝙷 %M𝚖 %S𝚜", time.gmtime(time.time() - Vars.PING))
  try:
    await retry_on_flood(message.reply_photo)(
      photo,
      caption=start_text.format(ping),
      reply_markup=InlineKeyboardMarkup(Start_Button),
      quote=True
    )
  except Exception:
    await retry_on_flood(message.edit_message_media)(
      media=InputMediaPhoto(photo, caption=start_text.format(ping)),
      reply_markup=InlineKeyboardMarkup(Start_Button)
    )


# Force-subscribe gate.  Runs in its own group (-1) *before* every other
# handler; it only stops propagation when the user still has to join.  (As a
# group-0 catch-all that swallowed ContinuePropagation it ended dispatch for
# all later private handlers, and its position depended on file-system order.)
@Bot.on_message(filters.private, group=-1)
async def on_private_message(client, message):
  channel = Vars.FORCE_SUB_CHANNEL
  if channel in ["None", None, "none", "OFF", False, "False", ""]:
    return

  if not client.FSB or client.FSB == [] or not message.from_user:
    return

  if message.from_user.id in Vars.ADMINS:
    return

  channel_button, change_data = await check_fsb(client, message)
  if not channel_button:
    return

  channel_button = split_list(channel_button)
  channel_button.append([InlineKeyboardButton("𝗥𝗘𝗙𝗥𝗘𝗦𝗛 ⟳", callback_data="refresh")])

  await retry_on_flood(message.reply_photo)(
      caption=Vars.FORCE_SUB_TEXT,
      photo=random.choice(Vars.PICS),
      reply_markup=InlineKeyboardMarkup(channel_button),
      quote=True,
  )
  if change_data:
    for change_ in change_data:
      client.FSB[change_[0]] = (change_[1], change_[2], change_[3])

  message.stop_propagation()





@Bot.on_message(filters.command("my_plan"))
async def my_plan(client, message):
  plan = await database.premium_user(message.from_user.id)
  if plan:
    xt = (plan["expiration_timestamp"] - (time.time()))
    x = round(xt / (24 * 60 * 60))

    await retry_on_flood(message.reply)(
      f"""
<i>Your Information:</i>

  <b>- User ID: {message.from_user.id}</b>
  <b>- Username: {message.from_user.username}</b>
  <b>- Days: {plan.get("days", "")}</b>
  <b>- Expiration Days: {x}</b> 

<i>Thanks For Buying It......</i>""",
      quote=True,
      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▏𝗖𝗟𝗢𝗦𝗘▕", callback_data="kclose")]])
    )

  else:
    await retry_on_flood(message.reply)(
      "<i> You Have No Plan!! </i>",
      reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(" Buy Now ", callback_data="premuim")]
      ]))


@Bot.on_message(filters.command(["clean", "clean_tasks", "clean_queue"]) & filters.private)
async def deltask(client, message):
  """/clean - cancel the running task and drop the waiting ones of THIS user (bot DM only).
  Admins: `/clean all` does it for every user's tasks.  Channel auto-posts are never touched
  (manage those with /manage)."""
  if Vars.IS_PRIVATE and message.chat.id not in Vars.ADMINS:
    return await message.reply("<code>You cannot use me baby </code>")

  arg = (message.command[1].lower() if len(message.command) > 1 else "")
  users = [message.from_user.id]
  if arg == "all" and message.from_user.id in Vars.ADMINS:
    users = {int(t.user_id) for t, _ in queue.storage_data.values() if getattr(t, "kind", "user") == "user"}
    users |= {int(t.user_id) for t in queue.ongoing_tasks.values() if getattr(t, "kind", "user") == "user"}
    users = list(users)

  pending = running = 0
  for uid in users:
    p_, r_ = await queue.cancel_user(uid)
    pending, running = pending + p_, running + r_

  if pending or running:
    await message.reply(f"<i>Cleaned: {running} running task cancelled, {pending} waiting task(s) removed.</i>")
  else:
    await message.reply("<i>You have nothing running or waiting.</i>")



@Bot.on_message(filters.command(["add_premium", "add_admin"]))
async def add_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  sts = await msg.reply_text("<code>Processing...</code>")
  try:
    parts = msg.text.split()
    user_id = int(parts[1])
    if parts[0].lstrip("/").split("@")[0] == "add_premium":
      time_limit_days = int(parts[2])
      await database.add_premium(user_id, time_limit_days)
      await retry_on_flood(sts.edit)("<code>User added to premium successfully.</code>")
      try:
        await retry_on_flood(_.send_message)(
          user_id,
          f"<i>You are now a premium user for {time_limit_days} days... Thanks For Buying It.....</i>"
        )
      except Exception:
        pass

    else:
      if user_id not in Vars.ADMINS:
        Vars.ADMINS.append(user_id)  # runtime only: add the id to ADMINS to keep it after a restart
      await retry_on_flood(sts.edit)("<code>User added to admin until restart (put the id in ADMINS to keep it).</code>")

  except (IndexError, ValueError):
    await retry_on_flood(sts.edit)("<code>Usage: /add_premium &lt;user_id&gt; &lt;days&gt;  |  /add_admin &lt;user_id&gt;</code>")
  except Exception as err:
    await retry_on_flood(sts.edit)(str(err))


@Bot.on_message(filters.command(["del_premium"]))
async def del_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  sts = await msg.reply_text("<code>Processing...</code>")
  try:
    user_id = int(msg.text.split(" ")[1])
    await database.remove_premium(user_id)
    await retry_on_flood(sts.edit)("<code>User removed from premium successfully.</code>")
    try:
      await retry_on_flood(_.send_message)(
        user_id,
        "<i>Your Premuims Plans End.. Please Buy again or Contact To Owner....  .</i>"
      )
    except Exception:
      pass

  except Exception as err:
    await retry_on_flood(sts.edit)(str(err))


@Bot.on_message(filters.command(["del_expired", "del_expired_premium"]))
async def del_expired_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  sts = await msg.reply_text("<code>Processing...</code>")
  try:
    await database.remove_expired_users()
    await retry_on_flood(sts.edit)("<code>Expired users removed successfully.</code>")
  except Exception as err:
    await retry_on_flood(sts.edit)(str(err))


@Bot.on_message(filters.command(["premium", "premium_users"]))
async def premium_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  parts = msg.text.split()
  sub = parts[1].lower() if len(parts) > 1 else "list"
  if sub in ("add", "remove"):
    try:
      uid = int(parts[2])
      if sub == "add":
        days = int(parts[3])
        await database.add_premium(uid, days)
        text = f"<code>{uid}</code> is premium for {days} day(s)."
        notice = f"<i>You are now a premium user for {days} days. Thanks!</i>"
      else:
        await database.remove_premium(uid)
        text = f"<code>{uid}</code> removed from premium."
        notice = "<i>Your premium plan has ended.</i>"
      await msg.reply_text(text)
      try:
        await _.send_message(uid, notice)
      except Exception:
        pass
    except (IndexError, ValueError):
      await msg.reply_text("Usage: <code>/premium add &lt;id&gt; &lt;days&gt;</code> · "
                           "<code>/premium remove &lt;id&gt;</code> · <code>/premium list</code>")
    return

  sts = await msg.reply_text("<code>Processing...</code>")
  try:
    txt = "<b>Premium Users:-</b>\n"
    async for user_ids, data in database.get_all_premium():
      try:
        user_info = await _.get_users(user_ids)
        username = user_info.username
        first_name = user_info.first_name
      except Exception:
        username = "N/A"
        first_name = "N/A"

      expiration_timestamp = data["expiration_timestamp"]
      xt = (expiration_timestamp - (time.time()))
      x = round(xt / (24 * 60 * 60))
      txt += f"User id: <code>{user_ids}</code>\nUsername: @{username}\nName: <code>{first_name}</code>\nExpiration Timestamp: {x} days\n"

    await retry_on_flood(sts.edit)(txt[:4000])
  except Exception as err:
    await retry_on_flood(sts.edit)(str(err))


@Bot.on_message(filters.command(["broadcast", "b"]))
async def b_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  return await borad_cast_(_, msg)


@Bot.on_message(filters.command(["pbroadcast", "pb"]))
async def pb_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  return await borad_cast_(_, msg, pin=True)

@Bot.on_message(filters.command(["forward", "fd"]))
async def fb_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  return await borad_cast_(_, msg, forward=True)

@Bot.on_message(filters.command(["pforward", "pfd"]))
async def pfb_handler(_, msg):
  if msg.from_user.id not in Vars.ADMINS:
    return

  return await borad_cast_(_, msg, pin=True, forward=True)

async def borad_cast_(_, message, pin=None, forward=None):
  sts = await message.reply_text("<code>Processing...</code>")
  if message.reply_to_message:
    msg = message.reply_to_message
    total = 0
    successful = 0
    blocked = 0
    deleted = 0
    unsuccessful = 0

    await retry_on_flood(sts.edit)("<code>Broadcasting...</code>")

    async for user_data in database.get_users():
      try:
        user_id = user_data.get("_id")
        if not user_id:
          continue
        total += 1

        if forward:
          docs = await retry_on_flood(msg.forward)(int(user_id))
        else:
          docs = await retry_on_flood(msg.copy)(int(user_id))

        if pin:
          await retry_on_flood(docs.pin)(both_sides=True)

        successful += 1

      except pyrogram.errors.UserIsBlocked:
        blocked += 1
      except pyrogram.errors.PeerIdInvalid:
        unsuccessful += 1
      except pyrogram.errors.InputUserDeactivated:
        deleted += 1
      except pyrogram.errors.UserNotParticipant:
        blocked += 1
      except Exception:
        unsuccessful += 1

    status = f"""<b><u>Broadcast Completed</u>

Total Users: <code>{total}</code>
Successful: <code>{successful}</code>
Blocked Users: <code>{blocked}</code>
Deleted Accounts: <code>{deleted}</code>
Unsuccessful: <code>{unsuccessful}</code></b>"""

    await retry_on_flood(sts.edit)(status)
  else:
    await retry_on_flood(sts.edit)("<code>Reply to a message to broadcast it.</code>")


@Bot.on_message(filters.command("restart"))
async def restart_(client, message):
  if message.from_user.id not in Vars.ADMINS:
    return

  sts = await message.reply_text("<code>Restarting....</code>", quote=True)
  with open("restart_msg.txt", "w") as f:
    f.write(f"{sts.chat.id}:{sts.id}")  # bot.py edits this message after start-up
  await (await create_subprocess_exec(executable, "update.py")).wait()
  execl(executable, executable, "-B", "main.py")


@Bot.on_message(filters.command("update"))
async def update_bot(client, message):
  if message.from_user.id not in Vars.ADMINS:
    return

  try:
      msg = await retry_on_flood(message.reply_text)("<b><blockquote>Pulling the latest updates and restarting the bot...</blockquote></b>")

      # UPSTREAM_REPO set (private repo + token + UPSTREAM_BRANCH) -> same logic as the start-up update;
      # otherwise a plain `git pull` of the current checkout
      if os.environ.get("UPSTREAM_REPO", "").strip():
        git_pull = await asyncio.to_thread(
          subprocess.run, [executable, "update.py"], capture_output=True, text=True
        )
        if "Successfully updated" not in (git_pull.stdout or ""):
          git_pull.returncode = 1
          git_pull.stderr = (git_pull.stdout or git_pull.stderr or "update failed")[-800:]
      else:
        git_pull = await asyncio.to_thread(
          subprocess.run, ["git", "pull"], capture_output=True, text=True
        )

      if git_pull.returncode == 0:
            await retry_on_flood(msg.edit_text)(f"<b><blockquote>Updates pulled successfully:\n\n{git_pull.stdout}</blockquote></b>")
      else:
            await retry_on_flood(msg.edit_text)(f"<b><blockquote>Failed to pull updates:\n\n{git_pull.stderr}</blockquote></b>")
            return

      await asyncio.sleep(3)

      await retry_on_flood(msg.edit_text)("<b><blockquote>✓ Bᴏᴛ ɪs ʀᴇsᴛᴀʀᴛɪɴɢ ɴᴏᴡ...</blockquote></b>")

  except Exception as e:
        await retry_on_flood(message.reply_text)(f"An error occurred: {e}")
        return

  # only reached when the pull succeeded (it used to restart even after a failed pull)
  execl(executable, executable, "-B", "main.py")


def humanbytes(size):
  if not size:
    return ""
  units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
  size = float(size)
  i = 0
  while size >= 1024.0 and i < len(units) - 1:
    i += 1
    size /= 1024.0
  return "%.2f %s" % (size, units[i])


def get_process_stats():
  p = psutil.Process(os.getpid())
  try:
      cpu = p.cpu_percent(interval=0.5)
  except Exception:
      cpu = "N/A"
  try:
      mem_info = p.memory_info()
      rss = humanbytes(mem_info.rss)
      vms = humanbytes(mem_info.vms)
  except Exception:
      rss = vms = "N/A"
  return (
      f" ├ CPU: {cpu}%\n"
      f" ├ RAM (RSS): {rss}\n"
      f" └ RAM (VMS): {vms}"
  )

@Bot.on_message(filters.command('stats'))
async def show_stats(client, message):
  if message.from_user.id not in Vars.ADMINS:
    return
  total_disk, used_disk, free_disk = shutil.disk_usage(".")
  total_disk_h = humanbytes(total_disk)
  used_disk_h = humanbytes(used_disk)
  free_disk_h = humanbytes(free_disk)
  disk_usage_percent = psutil.disk_usage('/').percent

  net_start = psutil.net_io_counters()
  await asyncio.sleep(2)  # (time.sleep froze the whole bot for 2s on every /stats)
  net_end = psutil.net_io_counters()

  bytes_sent = net_end.bytes_sent - net_start.bytes_sent
  bytes_recv = net_end.bytes_recv - net_start.bytes_recv

  cpu_cores = os.cpu_count()
  cpu_usage = psutil.cpu_percent()

  ram = psutil.virtual_memory()
  ram_total = humanbytes(ram.total)
  ram_used = humanbytes(ram.used)
  ram_free = humanbytes(ram.available)
  ram_usage_percent = ram.percent

  try:
    uptime_seconds = time.time() - Vars.PING
    uptime = time.strftime("%Hh %Mm %Ss", time.gmtime(uptime_seconds))
  except Exception:
    uptime = "N/A"

  start_time = time.time()
  status_msg = await message.reply('▤ **Accessing System Details...**')
  end_time = time.time()
  time_taken_ms = int((end_time - start_time) * 1000)

  os_name = platform.system()
  os_version = platform.release()
  python_version = platform.python_version()

  response_text = f"""
▣ **System Statistics Dashboard**

▣ **Disk Storage**
├ Total:  `{total_disk_h}`
├ Used:  `{used_disk_h}` ({disk_usage_percent}%)
└ Free:  `{free_disk_h}`

◈ **RAM (Memory)**
├ Total:  `{ram_total}`
├ Used:  `{ram_used}` ({ram_usage_percent}%)
└ Free:  `{ram_free}`

ϟ **CPU**
├ Cores:  `{cpu_cores}`
└ Usage:  `{cpu_usage}%`

ϟ **Bot Process**
{get_process_stats()}

◍ **Network**
├ Upload Speed:  `{humanbytes(bytes_sent/2)}/s`
├ Download Speed:  `{humanbytes(bytes_recv/2)}/s`
└ Total I/O:  `{humanbytes(net_end.bytes_sent + net_end.bytes_recv)}`

▣ **System Info**
├ OS:  `{os_name}`
├ OS Version:  `{os_version}`
├ Pyrofork Version:  `{pyrogram.__version__}`
├ Python:  `{python_version}`
└ Uptime:  `{uptime}`

◔ **Performance**
└ Current Ping:  `{time_taken_ms:.3f} ms`
"""
  try:
    from Tools import control as _control
    response_text += _control.stats_text(await _control.bot_stats())
  except Exception as err:
    logger.warning(f"bot stats failed: {err}")

  await retry_on_flood(message.reply_text)(response_text, quote=True)
  await retry_on_flood(status_msg.delete)()


@Bot.on_message(filters.command("shell"))
async def shell(_, message):
  if message.from_user.id not in Vars.ADMINS:
    return

  cmd = message.text.split(maxsplit=1)
  if len(cmd) == 1:
    return await retry_on_flood(message.reply)("<code>No command to execute was given.</code>")

  cmd = cmd[1]
  proc = await asyncio.create_subprocess_shell(
    cmd, stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE
  )
  stdout, stderr = await proc.communicate()
  stdout = stdout.decode().strip()
  stderr = stderr.decode().strip()
  reply = ""
  if len(stdout) != 0:
    reply += f"<b>Stdout</b>\n<blockquote>{stdout}</blockquote>\n"
  if len(stderr) != 0:
    reply += f"<b>Stderr</b>\n<blockquote>{stderr}</blockquote>"

  if len(reply) > 3000:
    bio = BytesIO()
    bio.write(str(reply).encode('utf-8'))
    bio.seek(0)

    await retry_on_flood(message.reply_document)(bio, file_name="shell_output.txt")
    bio.close()

  elif len(reply) != 0:
    await retry_on_flood(message.reply)(reply)
  else:
    await retry_on_flood(message.reply)("No Reply")





async def old_help(client, message):          # replaced by TG/guide.py (interactive help center)
  try:
    if Vars.IS_PRIVATE and message.chat.id not in Vars.ADMINS:
      return await message.reply("<code>You cannot use me baby </code>")
  except Exception:
    pass

  try:
    await retry_on_flood(message.reply)(HELP_MSG)
  except Exception:
    await retry_on_flood(message.edit_message_text)(
      HELP_MSG,
      reply_markup=InlineKeyboardMarkup(help_button)
    )



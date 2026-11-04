from Webs import web_data


from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
import asyncio
import pyrogram.errors
from pyrogram.errors import FloodWait
from bot import Vars
from loguru import logger
from pyrogram import Client, filters

from Tools.base import queue, igrone_error, get_episode_number, retry_on_flood, TTLCache



searchs = TTLCache(default_timeout=7200, cleanup_interval=60)
backs = TTLCache(default_timeout=7200, cleanup_interval=60)
chaptersList = TTLCache(default_timeout=7200, cleanup_interval=60)
_storage = TTLCache(default_timeout=7200, cleanup_interval=60)
pagination = TTLCache(default_timeout=7200, cleanup_interval=60)
subscribes = TTLCache(default_timeout=7200, cleanup_interval=60)

Listeing_cache = {}

web_data = dict(sorted(web_data.items()))
plugins_name = " ".join(web_data[i].sf for i in web_data)

def split_list(li):
    return [li[x:x + 2] for x in range(0, len(li), 2)]


def is_listening_(flt, _, message: Message):
    str_id = str(message.from_user.id)
    if flt.is_private and str_id in Listeing_cache: # adding channels
        if message.text == "/stop":
            return False

        elif flt.forwarded:
            return True

    return False




def check_get_web(url):
    if not url:
        return None

    for web in web_data.values():
        if url.startswith(web.url):
            return web



def is_auth_query():
    async def func(flt, _, query):
        reply = query.message.reply_to_message
        if not reply:
            return True

        if not reply.from_user:
            return False

        user_id = reply.from_user.id
        query_user_id = query.from_user.id
        if user_id != query_user_id:
            await query.answer("This is not for you", show_alert=True)
            return False
        return True

    return filters.create(func)


def plugins_list(type=None, page=1):
    button = []
    if type and type == "updates":
        for i in web_data.keys():
            c = web_data[i].sf
            c = f"udat_{c}"
            button.append(InlineKeyboardButton(i, callback_data=c))
    elif type and type == "gens":
        for i in web_data.keys():
            c = web_data[i].sf
            c = f"gens_{c}"
            button.append(InlineKeyboardButton(i, callback_data=c))
    elif type and type == "subs":
        for i in web_data.keys():
            c = web_data[i].sf
            c = f"isubs_{c}"
            button.append(InlineKeyboardButton(i, callback_data=c))
    else:
        for i in web_data.keys():
            c = web_data[i].sf
            c = f"plugin_{c}"
            button.append(InlineKeyboardButton(i, callback_data=c))

    if len(button) > 30:
        button = button[len(button)//2:len(button)] if page != 1 else button[:len(button)//2]
        button = split_list(button)
        button.append([
            InlineKeyboardButton(" >> ", callback_data="bk.p:2") if page == 1 else InlineKeyboardButton(" << ", callback_data="bk.p:1")
        ])
    else:
        button = split_list(button)

    button.append([
        InlineKeyboardButton("♞ All Search ♞", callback_data="plugin_all"),
        InlineKeyboardButton("✹ Close ✹", callback_data="kclose")
    ])
    return InlineKeyboardMarkup(button)

def get_webs(sf):
    return next((web for web in web_data.values() if web.sf == sf), None)



async def check_fsb(client, message):
    channel_button = []

    for channel_info in client.FSB:
        try:
            channel = int(channel_info[1])
        except Exception:
            channel = channel_info[1]

        try:
            await client.get_chat_member(channel, message.from_user.id)
        except pyrogram.errors.UserNotParticipant:
            channel_link = channel_info[2] if len(channel_info) > 2 else (
                await client.export_chat_invite_link(channel) if isinstance(channel, int) 
                else f"https://telegram.me/{str(channel).strip()}"
            )
            channel_button.append(InlineKeyboardButton(channel_info[0], url=channel_link))
        except (pyrogram.errors.UsernameNotOccupied, pyrogram.errors.ChatAdminRequired) as e:
            if Vars.LOG_CHANNEL:
                await igrone_error(client.send_message)(
                    Vars.LOG_CHANNEL, f"Channel issue: {channel} - {type(e).__name__}"
                )
        except (pyrogram.ContinuePropagation, pyrogram.StopPropagation):
            raise
        except Exception as e:
            if Vars.LOG_CHANNEL:
                await igrone_error(client.send_message)(
                    Vars.LOG_CHANNEL, f"Force Subscribe error: {e} at {channel}"
                )

    return channel_button, []


# Optimized utility functions
def clean(txt, length=-1):
    """Clean text by removing special characters"""
    txt = txt.translate(str.maketrans('', '', "_&;:None'|*?><`!@#$%^~+=\\/\n"))
    return txt[:length] if length != -1 else txt


def select_preferred_chapters(chapters_raw):
  """Selects the preferred chapters based on the scanlator slugs."""
  PREFERRED_SCANLATOR_SLUGS = [
      "official",
      "utoon",
      "templescan",
      "lunatoon",
      "magusmanga",
      "asura",
      "asurascan",
      "violetscan",
      "luacomic",
  ]

  chapters_by_number = {}  # chapter number: [chapters]
  for chap in chapters_raw:
      chap_num = get_episode_number(chap.get("title", ""))
      if chap_num is None or float(chap_num) == 0:
          continue

      chapters_by_number.setdefault(str(chap_num), []).append(chap)

  selected_tuples = []
  for chap_num_str, group in chapters_by_number.items():
      found = None
      best_priority = len(PREFERRED_SCANLATOR_SLUGS)

      for chap in group:
          scan_group = str(chap.get("group_name", "")).lower()
          if scan_group in PREFERRED_SCANLATOR_SLUGS:
              priority = PREFERRED_SCANLATOR_SLUGS.index(scan_group)
              if (found is None) or (priority < best_priority):
                  found = chap
                  best_priority = priority

      if found:
          selected_tuples.append((float(chap_num_str), found))
      else:
          selected_tuples.append((float(chap_num_str), group[0]))


  try:
      selected_tuples.sort(key=lambda x: x[0])
      return [chapter_data for _, chapter_data in selected_tuples]
  except Exception:
      return [chapter_data for _, chapter_data in selected_tuples]
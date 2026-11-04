from Tools.base import MangaCard, TTLCache
from bot import  Bot, Vars, logger
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
import random

from Tools.db import database

from .storage import (
    get_webs, igrone_error, plugins_list, 
    retry_on_flood, searchs, is_auth_query, 
    web_data, check_get_web, Listeing_cache
)

from .subscribe import isubs_callback
from Tools.my_token import verify_token, get_token, check_token_
import asyncio


search_storage_cache = TTLCache(default_timeout=7200, cleanup_interval=60)

website_index = [
  instance.sf
  for key, instance in web_data.items()
  if hasattr(instance, 'sf')
]


@Bot.on_message(filters.command("search"))
@check_token_
async def search_group(client, message):
  if Vars.IS_PRIVATE:
    if message.chat.id not in Vars.ADMINS:
      return await retry_on_flood(message.reply)("<code>You cannot use me baby </code>")

  await database.ensure_user(message.from_user.id)

  try:
    message.text.split(" ")[1]
  except Exception:
    return await retry_on_flood(message.reply)("<code>Format:- /search Manga </code>")

  photo = random.choice(Vars.PICS)
  await retry_on_flood(message.reply_photo)(
    photo, caption="<i>Select search Webs ...</i>",
    reply_markup=plugins_list(), quote=True
  )



@Bot.on_message(filters.text & filters.private & ~filters.regex(r"^/"))
@check_token_
async def search(client, message):
  if str(message.from_user.id) in Listeing_cache:
    return message.continue_propagation()

  if Vars.IS_PRIVATE:
    if message.chat.id not in Vars.ADMINS:
      return await retry_on_flood(message.reply)("<code>You cannot use me baby </code>")

  await database.ensure_user(message.from_user.id)
  photo = random.choice(Vars.PICS)

  await retry_on_flood(message.reply_photo)(
    photo, caption="<i>Select search Webs ...</i>",
    reply_markup=plugins_list(), quote=True
  )


@Bot.on_callback_query(filters.regex("^bk|back_page") & is_auth_query())
async def bk_handler(client, query):
  """This Is Back Handler Of Callback Data"""
  photo = random.choice(Vars.PICS)
  try: 
    page = int(query.data.split(":")[-1])
  except Exception:
    page = 1

  await database.ensure_user(query.from_user.id)
  await retry_on_flood(query.message.edit_media)(
      media=InputMediaPhoto(photo, caption="<i>Select The Webs ....</i>"),
      reply_markup=plugins_list(page=page),
  )
  await igrone_error(query.answer)()


async def search_all(search, sts, max_concurrent=5):
  """Ultra-low RAM usage with streaming results"""
  semaphore = asyncio.Semaphore(max_concurrent)
  results = []
  found_websites = []
  not_found_websites = []
  processed_count = 0
  total_websites = len(web_data)

  async def search_and_collect(web_name, web):
      async with semaphore:
          try:
              result = await web.search(search)
              if result:
                  found_websites.append(web_name)
                  return result
              else:
                  not_found_websites.append(web_name)
                  return []
          except Exception:
              not_found_websites.append(web_name)
              return []

  # Create all tasks at once
  tasks = [search_and_collect(name, web) for name, web in web_data.items()]

  for i, task in enumerate(asyncio.as_completed(tasks), 1):
      result = await task
      if result:
          results.extend(result)

      processed_count += 1
      web_name = list(web_data.keys())[i-1]
      await igrone_error(sts.edit_message_caption)(
          f"<i>Searching: <b>{search}</b> | "
          f"Progress: <b>{processed_count}/{total_websites}</b> | "
          f"Webs: <b>{web_name}</b></i>"
      )


  found_text = ", ".join(found_websites) if found_websites else None
  not_found_text = ", ".join(not_found_websites) if not_found_websites else None

  return results, found_text, not_found_text



def paginate_results(results, page=1, items_per_page=15):
      """Helper function to paginate results"""
      if not results:
          return None

      start_idx = (page - 1) * items_per_page
      end_idx = page * items_per_page

      return results[start_idx:end_idx]

@Bot.on_callback_query(filters.regex("^plugin_") & is_auth_query())
async def cb_handler(client, query):
    """Search Handler Of Callback Data"""
    callback_type = query.data

    data_parts = str(callback_type).split('_')

    photo = random.choice(Vars.PICS)
    results = None
    all_results = None
    found_sites = None
    not_found_sites = None

    try:
      page = int(data_parts[-2]) #if len(data_parts) > 2 else 1
    except (ValueError, IndexError, Exception):
      page = 1

    if "/" in callback_type:
      try:
          data_idx = int(callback_type.split("/")[-1])
          data = website_index[data_idx]
      except (ValueError, IndexError):
          data = website_index[-1]
    else:
      data = data_parts[-1]

    await asyncio.sleep(0.2)
    reply_msg = query.message.reply_to_message

    websites = get_webs(data)
    if not websites:
        websites = "all"

    website_id = websites if isinstance(websites, str) else getattr(websites, 'sf', str(websites))

    try:
      website_index_pos = website_index.index(website_id)
    except ValueError:
      website_index_pos = 0

    search_text = str(reply_msg.text) if hasattr(reply_msg, 'text') else None

    if websites == "all":
        website_name = "All"
    else:
        website_name = type(websites).__name__.replace("Webs", "").replace("Website", "").replace("Source", "")

    if search_text is None:
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("𝘊𝘰𝘶𝘭𝘥𝘯'𝘵 𝘧𝘪𝘯𝘥 𝘢𝘯𝘺 𝘮𝘢𝘯𝘨𝘢.", callback_data="just_kidding")
            ],
            [
                InlineKeyboardButton(
                    "⇇ Prev Webs ", 
                    callback_data=f"plugin_/{website_index_pos-1}"
                ),
                InlineKeyboardButton(
                    " Next Webs ⇉", 
                    callback_data=f"plugin_/{website_index_pos+1}"
                )
            ],
            [
                InlineKeyboardButton("▏CLOSE▕", callback_data="close"),
                InlineKeyboardButton("⇦ BACK", callback_data="back_page"),
            ]
        ])
        caption = f"<blockquote><i>No results found for: <b>{search_text}</b> on {website_name}</i></blockquote>"

        await retry_on_flood(query.edit_message_media)(
              InputMediaPhoto(photo, caption=caption),
              reply_markup=reply_markup
        )
        return


    if any(cmd in search_text.lower() for cmd in ["/subs", "/subscribes", "/queue"]):
          try:
              return await isubs_callback(client, query)
          except Exception as err:
              logger.exception(f"Error in isubs_callback: {err}")
              await igrone_error(query.answer)("An error occurred", show_alert=True)
              await retry_on_flood(query.message.delete)()
              return

    if search_text.startswith("/search"):
      search_query = search_text.split(" ", 1)[-1].strip()
    else:
      search_query = search_text.strip()


    await database.ensure_user(query.from_user.id)
    await igrone_error(query.edit_message_caption)(
          f"<i>Searching: <b>{search_query}</b>  </i>"
    )


    if (website_id in search_storage_cache and search_query in search_storage_cache[website_id]):
        all_results, found_sites, not_found_sites = search_storage_cache[website_id][search_query]

    elif websites == "all":
        all_results, found_sites, not_found_sites = await search_all(search_query, query)
        search_storage_cache.setdefault(website_id, {})
        search_storage_cache[website_id][search_query] = (all_results, found_sites, not_found_sites)

    else:
        try:
            all_results = await asyncio.wait_for(websites.search(search_query), 120)
            search_storage_cache.setdefault(website_id, {})
            search_storage_cache[website_id][search_query] = (all_results, found_sites, not_found_sites)
        except Exception as e:
            logger.error(f"Error searching {website_id}: {e}")
            all_results = []

    results = paginate_results(all_results, page)

    if not results or not all_results:
      reply_markup = InlineKeyboardMarkup([
          [
              InlineKeyboardButton("𝘊𝘰𝘶𝘭𝘥𝘯'𝘵 𝘧𝘪𝘯𝘥 𝘢𝘯𝘺 𝘮𝘢𝘯𝘨𝘢.", callback_data="just_kidding")
          ],
          [
              InlineKeyboardButton(
                "⇇ Prev Webs ", 
                callback_data=f"plugin_/{website_index_pos-1}"
              ),
              InlineKeyboardButton(
                " Next Webs ⇉", 
                callback_data=f"plugin_/{website_index_pos+1}"
              )
          ],
          [
              InlineKeyboardButton("▏CLOSE▕", callback_data="close"),
              InlineKeyboardButton("⇦ BACK", callback_data="back_page"),
          ]
      ])

      caption = f"<blockquote><i>No results found for: <b>{search_query}</b> on {website_name}</i></blockquote>"


      await retry_on_flood(query.edit_message_caption)(
          caption=caption, reply_markup=reply_markup
      )
      return

    buttons = []
    for result in results:
      if not isinstance(result, MangaCard):
          result = MangaCard.from_dict(result)


      result_id = result.data.get('id') or hash(result.url)
      callback_data = f"chs|{data}{result_id}"

      if websites == "all":
          result_website = check_get_web(result.url)
          if not result_website:
              continue

          if result_website:
              result.webs = result_website
              searchs[callback_data] = result
              site_name = type(result_website).__name__.replace("Webs", "").replace("Website", "").replace("Source", "")
              button_text = f"{result.title} [{site_name}]"
          else:
              continue
      else:
          result.webs = websites
          searchs[callback_data] = result
          button_text = result.title

      buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    await igrone_error(query.answer)()

    nav_buttons = []
    if paginate_results(all_results, page - 1):
        nav_buttons.append(InlineKeyboardButton("<< ", callback_data=f"plugin_{page-1}_{data}"))

    if paginate_results(all_results, page - 2) and page != 1:
        nav_buttons.append(InlineKeyboardButton("<< 2x", callback_data=f"plugin_{page-2}_{data}"))

    if paginate_results(all_results, page + 2):
        nav_buttons.append(InlineKeyboardButton("2x >>", callback_data=f"plugin_{page+2}_{data}"))

    if paginate_results(all_results, page + 1):
        nav_buttons.append(InlineKeyboardButton(" >>", callback_data=f"plugin_{page+1}_{data}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton(
            "⇇ Previous Websites",
            callback_data=f"plugin_/{website_index_pos-1}"
        ),
        InlineKeyboardButton(
            "Next Websites ⇉", 
            callback_data=f"plugin_/{website_index_pos+1}"
        )
    ])

    buttons.append([
        InlineKeyboardButton("▏CLOSE▕", callback_data="close"),
        InlineKeyboardButton("⇦ BACK", callback_data="back_page"),
    ])

    caption_parts = [f"<blockquote><i>Search results for: <b>{search_query}</b> from <b>{website_name}</b></i></blockquote>"]
    if websites == "all":
      if found_sites:
          caption_parts.append(f"\n<blockquote expandable><b>Found Sites:</b> <i>{found_sites}</i></blockquote>")

      if not_found_sites:
          caption_parts.append(f"\n<blockquote expandable><b>Sites with no results:</b> <i>{not_found_sites}</i></blockquote>")

    caption = "".join(caption_parts)[:1024]
    try:
        await retry_on_flood(query.edit_message_media)(
          InputMediaPhoto(photo, caption=caption),
          reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
      logger.error(f"Error updating message: {e}")
      await retry_on_flood(query.edit_message_caption)(
        caption=caption,
        reply_markup=InlineKeyboardMarkup(buttons),
      )
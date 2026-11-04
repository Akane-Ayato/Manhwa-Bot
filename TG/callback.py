from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from .storage import (
   searchs, pagination, subscribes, _storage,
   retry_on_flood, igrone_error, check_fsb, queue,
   split_list, chaptersList, get_episode_number, is_auth_query,
)

from bot import Bot, Vars, logger
import random

from Tools.db import database
from Tools.base import Subscribes, TaskCard, MangaCard
import asyncio


@Bot.on_callback_query(filters.regex("^just_kidding$"))
async def just_kidding_handler(_, query):
  await igrone_error(query.answer)("♡  𝗛𝗼𝗻𝘁𝗼 𝗻𝗶 𝗮𝗿𝗶𝗴𝗮𝘁𝗼 𝗴𝗼𝘇𝗮𝗶𝗺𝗮𝘀𝘂....  ♡")


@Bot.on_callback_query(filters.regex("^refresh$"))
async def refresh_handler(_, query):
  if not _.FSB or _.FSB == []:
    await retry_on_flood(query.answer)(
      " ✓ Thanks for joining! You can now use the bot. ",
      show_alert=True
    )
    return await retry_on_flood(query.message.delete)()

  channel_button, change_data = await check_fsb(_, query)
  if not channel_button:
    await retry_on_flood(query.answer)(
      " ✓ Thanks for joining! You can now use the bot. ",
      show_alert=True
    )

    return await retry_on_flood(query.message.delete)()

  channel_button = split_list(channel_button)
  channel_button.append([InlineKeyboardButton("ʀᴇғʀᴇsʜ ⟳", callback_data="refresh")])

  try:
    await retry_on_flood(query.edit_message_media)(
        media=InputMediaPhoto(random.choice(Vars.PICS),
                              caption=Vars.FORCE_SUB_TEXT),
        reply_markup=InlineKeyboardMarkup(channel_button),
    )
  except Exception:
    await retry_on_flood(query.answer)("You're still not in the channel.")

  if change_data:
    for change_ in change_data:
      _.FSB[change_[0]] = (change_[1], change_[2], change_[3])



@Bot.on_callback_query(filters.regex("^(close|kclose)$"))
async def close_handler(_, query):
  await igrone_error(query.answer)()
  try: 
    await retry_on_flood(query.message.reply_to_message.delete)()
  except Exception: 
    pass

  try:
    await retry_on_flood(query.message.delete)()
  except Exception:
    pass





@Bot.on_callback_query(filters.regex("^premuim$"))
async def premuim_handler(_, query):
  """This Is Premuim Handler Of Callback Data"""
  button = query.message.reply_markup.inline_keyboard
  text = """
<b><i>Premium Price

Pricing Rates
  7 Days - 30 inr / 0.35 USD / NRS 40
  1 Month - 90 inr / 1.05 USD / NRS 140
  3 Months - 260 inr / 2.94 USD / NRS 350
  6 Months - 500 inr / 6.33 USD / NRS 700
  9 Months - 780 inr / 9.14 USD / NRS 1100
  12 Months - 1000 inr / 11.8 USD / NRS 1400

Want To Buy ?!
  Contact or DM - @Shanks_Pro

We Have Limited Seats For Premium Users</i></b>"""
  try:
    del button[-2]
    await retry_on_flood(query.edit_message_media)(
      media=InputMediaPhoto(random.choice(Vars.PICS), caption=text),
      reply_markup=InlineKeyboardMarkup(button)
    )
  except Exception:
    button = [[InlineKeyboardButton(" Close ", callback_data="kclose")]]
    await retry_on_flood(query.edit_message_media)(
      media=InputMediaPhoto(random.choice(Vars.PICS), caption=text),
      reply_markup=InlineKeyboardMarkup(button)
    )



@Bot.on_callback_query(filters.regex("^chs") & is_auth_query())
async def ch_handler(client, query):
  """This Is Information Handler Of Callback Data"""
  try:
    manga_card: MangaCard = searchs[query.data]

    new_callback = str(query.data).replace("chs", "pg", 1)
  except Exception:
    return await query.answer(
      "This is an old button, please redo the search",
      show_alert=True
    )

  if not manga_card.chapters:
    try:
      data = manga_card.load_to_dict()
      bio_list = await asyncio.wait_for(
        manga_card.webs.get_chapters(data),
        timeout=180
      )

      manga_card.update_dict(bio_list)

      try:
        manga_card.chapters = await asyncio.wait_for(
          manga_card.webs.iter_chapters(bio_list, page=1), # iter all chapters at once
          timeout=180
        )
      except TypeError:
        manga_card.chapters = await asyncio.wait_for(
          asyncio.to_thread(lambda: manga_card.webs.iter_chapters(bio_list, page=1)), # iter all chapters at once
          timeout=180
        )

      del bio_list
    except Exception as er:
      logger.exception(er)
      return await igrone_error(query.answer)("Site has been Updated")


  subs_bool = await database.get_subs(str(query.from_user.id), manga_card.url, manga_card.webs.sf)

  sdata = Subscribes(
    manga_url=manga_card.url,
    manga_title=manga_card.title,
    webs=manga_card.webs.sf,
    lastest_chapter=manga_card.chapters[0]['title'] if manga_card.chapters else ""
  )

  sc = f"subs:{hash(manga_card.url)}"
  subscribes[sc] = sdata


  rand_pic = manga_card.poster or random.choice(Vars.PICS)

  caption = manga_card.msg[:1024] if manga_card.msg else f"<b>{manga_card.title}</b>"

  if manga_card.webs.sf in ("cx"):
    scans_callback = f"scg:{manga_card.webs.sf}:{hash(manga_card.chapters[-1]['url'])}"
    _storage[scans_callback] = (manga_card)

    button = [
      [
        InlineKeyboardButton("▸ ᴄʜᴀᴘᴛᴇʀs ◂", callback_data=new_callback),
        InlineKeyboardButton("▸ ꜱᴄᴀɴʟᴀᴛɪᴏɴ ɢʀᴏᴜᴘ ◂", callback_data=scans_callback),
      ],
      [
        InlineKeyboardButton("✘ ᴜɴsᴜʙsᴄʀɪʙᴇ ✘", callback_data=sc) if subs_bool else InlineKeyboardButton("✓ sᴜʙsᴄʀɪʙᴇ ✓", callback_data=sc)
      ],
      [
        InlineKeyboardButton("⇦ 𝗕𝗔𝗖𝗞", callback_data=f"plugin_{manga_card.webs.sf}"),
        InlineKeyboardButton("▏𝗖𝗟𝗢𝗦𝗘▕", callback_data="kclose")
      ]
    ]
  else:
    button = [
      [
        InlineKeyboardButton("✘ ᴜɴsᴜʙsᴄʀɪʙᴇ ✘", callback_data=sc) if subs_bool else InlineKeyboardButton("✓ sᴜʙsᴄʀɪʙᴇ ✓", callback_data=sc)
      ],
      [
        InlineKeyboardButton("▸ ᴄʜᴀᴘᴛᴇʀs ◂", callback_data=new_callback),
        InlineKeyboardButton("⇦ 𝗕𝗔𝗖𝗞", callback_data=f"plugin_{manga_card.webs.sf}")
      ],
    ]

  try:
    await retry_on_flood(query.edit_message_media)(
      InputMediaPhoto(rand_pic, caption=caption),
      reply_markup=InlineKeyboardMarkup(button)
    )
  except Exception:
    await retry_on_flood(query.edit_message_media)(
      InputMediaPhoto(Vars.PICS[-1], caption=caption),
      reply_markup=InlineKeyboardMarkup(button)
    )



def _iterate_chapters_(chapters: list, page: int) -> list:
  return chapters[(page - 1) * 40:page * 40] if page != 1 else chapters[:40]



def _create_chapters_button_(
  chapters: list, page: int, manga_card: MangaCard, 
  mode: bool = False, subs_bool: bool = False,
) -> list:
  button = []
  if not chapters:
    return button

  for chapter in _iterate_chapters_(chapters, int(page)):
    c = f"pic|{hash(chapter['url'])}"
    chaptersList[c] = (manga_card.webs, chapter)

    chapter_title = f"{chapter['title']} [{chapter['group_name']}]" if "group_name" in chapter and chapter['group_name'] else chapter['title']
    button.append(InlineKeyboardButton(chapter_title, callback_data=c))

  button = split_list(button)
  c = f"pg:{manga_card.webs.sf}:{hash(chapters[-1]['url'])}:"
  c += "m:" if mode else "n:"

  pagination[c] = (manga_card, []) if manga_card.chapters == chapters else (manga_card, chapters)

  if int(page) > 0:
    pre_page_ = []

    if int(int(page) - 1) > 0 and _iterate_chapters_(chapters, page=int(int(page) - 1)):
      pre_page_.append(InlineKeyboardButton("<<", callback_data=f"{c}{int(page) - 1}"))

    if int(int(page) - 2) > 0 and _iterate_chapters_(chapters, page=int(int(page) - 2)):
        pre_page_.append(InlineKeyboardButton("<2x", callback_data=f"{c}{int(page) - 2}"))

    if int(int(page) - 5) > 0 and _iterate_chapters_(chapters, page=int(int(page) - 5)):
        pre_page_.append(InlineKeyboardButton("<5x", callback_data=f"{c}{int(page) - 5}"))

    if pre_page_:
        button.append(pre_page_)


  next_page_ = []
  if _iterate_chapters_(chapters, page=int(int(page) + 1)):
    next_page_.append(InlineKeyboardButton(">>", callback_data=f"{c}{int(page) + 1}"))

  if _iterate_chapters_(chapters, page=int(int(page) + 2)):
    next_page_.append(InlineKeyboardButton("2x>", callback_data=f"{c}{int(page) + 2}"))

  if _iterate_chapters_(chapters, page=int(int(page) + 5)):
    next_page_.append(InlineKeyboardButton("5x>", callback_data=f"{c}{int(page) + 5}"))

  if next_page_:
    button.append(next_page_)

  all_data = f"full:{manga_card.webs.sf}:{hash(chapters[-1]['url'])}{hash(chapters[0]['url'])}"
  _storage[all_data] = (chapters, manga_card.webs)

  chapters = _iterate_chapters_(chapters, page=int(page))
  callback_data = f"full:{manga_card.webs.sf}:{len(chapters)}:{hash(chapters[0]['url'])}"
  _storage[callback_data] = (chapters, manga_card.webs)


  if manga_card.webs.sf in ("cx"):
    if mode:
      c = f"pg:{manga_card.webs.sf}:{hash(manga_card.chapters[-1]['url'])}:n:"
      pagination[c] = (manga_card, [])
      button.append([InlineKeyboardButton("♚ ᴄʜᴀᴘᴛᴇʀꜱ ♚", callback_data=c)])
    else:
      scans_callback = all_data.replace("full", "scg", 1)
      _storage[scans_callback] = (manga_card)
      button.append([InlineKeyboardButton("♚ ꜱᴄᴀɴʟᴀᴛɪᴏɴ ɢʀᴏᴜᴘ ♚", callback_data=scans_callback)])

  button.append([
    InlineKeyboardButton("⇧ ғᴜʟʟ ᴘᴀɢᴇ ⇧", callback_data=callback_data),
    InlineKeyboardButton("⇧ ᴀʟʟ ᴄʜᴀᴘᴛᴇʀꜱ ⇧", callback_data=all_data),
  ])

  sdata = Subscribes(
    manga_url=manga_card.url,
    manga_title=manga_card.title,
    webs=manga_card.webs.sf,
    lastest_chapter=manga_card.chapters[0]['title'] if manga_card.chapters else ""
  )
  c = f"subs:{hash(manga_card.url)}"
  subscribes[c] = sdata

  if manga_card.webs.sf != "dj":
    if subs_bool:
      button.append([InlineKeyboardButton("✘ ᴜɴsᴜʙsᴄʀɪʙᴇ ✘", callback_data=c)])
    else:
      button.append([InlineKeyboardButton("✓ sᴜʙsᴄʀɪʙᴇ ✓", callback_data=c)])

  button.append([
    InlineKeyboardButton("⇦ 𝗕𝗔𝗖𝗞", callback_data=f"plugin_{manga_card.webs.sf}"),
    InlineKeyboardButton("▏𝗖𝗟𝗢𝗦𝗘▕", callback_data="kclose")
  ])

  return button


@Bot.on_callback_query(filters.regex("^pg") & is_auth_query())
async def pg_handler(client, query):
  """This Is Pagination Handler Of Callback Data"""
  if (check_ := (str(query.data).replace("pg", "chs", 1))) in searchs:
    manga_card = searchs[check_]
    page = 1
    mode = False
    chapters = manga_card.chapters
  else:
    call_data = query.data.split(":")


    try:
      page = call_data[-1]
      mode = call_data[-2]
      mode = True if mode == "m" else False
      call_data = str(query.data).removesuffix(f"{page}")
    except Exception:
      call_data = "a"


    #logger.info(pagination)
    if call_data not in pagination:
      await igrone_error(query.answer)(
        "This is an old button, please redo the search",
        show_alert=True
      )
      return

    manga_card, chapters = pagination[call_data]
    if not chapters: chapters = manga_card.chapters


  try: 
    page = int(page)
  except Exception: 
    page = 1

  if not chapters or not _iterate_chapters_(chapters, int(page)):
    return await query.answer("No chapters found", show_alert=True)

  subs_bool = await database.get_subs(str(query.from_user.id), manga_card.url, manga_card.webs.sf)
  subs_bool = True if subs_bool else False

  button = _create_chapters_button_(
      chapters=chapters, page=int(page), 
      manga_card=manga_card, subs_bool=subs_bool, mode=mode,
  )
  if not button:
    return await igrone_error(query.answer)("No chapters found", show_alert=True)

  await retry_on_flood(query.edit_message_reply_markup)(InlineKeyboardMarkup(button))





@Bot.on_callback_query(filters.regex("^full") & is_auth_query())
async def full_handler(client, query):
  if query.data not in _storage:
    await retry_on_flood(query.answer)(
      "This is an old button, please redo the search",
      show_alert=True
    )
    return

  semaphore = asyncio.Semaphore(10)
  async def picture_scraping(webs, chapter):
    async with semaphore:
      return await asyncio.wait_for(
          webs.get_pictures(chapter['url'], data=chapter),
          timeout=120
      )

  chapters, webs = _storage[query.data]

  user_settings = asyncio.create_task(database.get_settings(query.from_user.id))
  priority = asyncio.create_task(database.premium_user(query.from_user.id))

  try:
    seen = set()
    chapters_list = []
    for chapter in reversed(chapters):
        ep = get_episode_number(chapter['title'])
        if ep not in seen:
          seen.add(ep)
          chapters_list.append(chapter)


    user_settings = await user_settings
    merge_size = user_settings.get('megre', None)

    # Convert merge_size to int if possible
    if merge_size:
          try:
              merge_size = int(merge_size)
          except (ValueError, TypeError):
              merge_size = 1

    merge_size = merge_size if merge_size else 1

    download_tasks = []
    for i in range(0, len(chapters_list), merge_size):
      chucks = chapters_list[i:i + merge_size]
      picturesList = [ asyncio.create_task(picture_scraping(webs, chuck)) for chuck in chucks ]
      download_tasks.append((chucks, picturesList))
      asyncio.gather(*picturesList)


    priority = await priority
    priority = 1 if priority else 0


    tasks = []
    for download in download_tasks:
      chapter, picturesList = download

      picturesList = await asyncio.gather(*picturesList, return_exceptions=True)

      flattened = []
      for pic in picturesList:
        if isinstance(pic, Exception):
          flattened = []
          break

        if isinstance(pic, list):
          flattened.extend(pic)
        else:
          flattened.append(pic)

      await asyncio.sleep(0.5)

      tasks.append(queue.put(
          TaskCard(
              data_list=chapter,
              picturesList=flattened,
              webs=webs,
              sts=None,
              user_id=query.from_user.id,
              chat_id=query.message.chat.id,
              priority=priority,
              settings=user_settings,
          )))


    if tasks:
      await asyncio.gather(*tasks)

    # Send success response
    await igrone_error(query.answer)(
      f"{len(tasks)} Chapter Added To Queue",
      show_alert=True
    )

  except Exception as err:
    logger.exception(err)
    await retry_on_flood(query.message.reply_text)(f"`{err}`")
    await igrone_error(query.answer)()



@Bot.on_callback_query(filters.regex("^pic") & is_auth_query())
async def pic_handler(client, query):
  """This Is Pictures Handler Of Callback Data"""
  if query.data in chaptersList:
    webs, data = chaptersList[query.data]
    user_id = query.from_user.id
    try:
      pictures = await webs.get_pictures(data['url'], data=data)
    except Exception as er:
      logger.exception(er)
      return await query.answer("No pictures found", show_alert=True)

    if not pictures:
      return await query.answer("No pictures found", show_alert=True)

    await database.ensure_user(user_id)

    sts = await retry_on_flood(query.message.reply_text)("<code>Adding...</code>")
    try:
      txt = f"<i>Manga Name: **{data['manga_title']}** Chapter: - **{data['title']}**</i>"
      priority = await database.premium_user(user_id)
      priority = 1 if priority else 0

      uts = await database.get_settings(user_id)
      task_id = await queue.put(
        TaskCard(
          data_list=[data.copy()],
          picturesList=pictures,
          webs=webs,
          sts=sts,
          user_id=query.from_user.id,
          chat_id=query.message.chat.id,
          priority=priority,
          settings=uts
        ),
      )

      button = [[InlineKeyboardButton(" Cancel Your Tasks ", callback_data=f"cql:{task_id}")]]
      await retry_on_flood(sts.edit)(txt, reply_markup=InlineKeyboardMarkup(button))

      await igrone_error(query.answer)(f"Your {task_id} added at queue")
    except Exception as err:
      logger.exception(err)
      await retry_on_flood(sts.edit)(f"`{str(err)}`")
      await igrone_error(query.answer)()
  else:
    await igrone_error(query.answer)("This is an old button, please redo the search", show_alert=True)


@Bot.on_callback_query(filters.regex("^cql"))
async def cl_handler(client, query):
  """This Is Cancel Handler Of Callback Data"""
  task_id = query.data.split(":")[-1]

  # only the owner of the request may cancel it (others in a group could before)
  reply = query.message.reply_to_message
  entry = queue.storage_data.get(task_id)
  if entry and int(entry[0].user_id) != query.from_user.id and query.from_user.id not in Vars.ADMINS:
    return await retry_on_flood(query.answer)("This is not for you", show_alert=True)

  if await queue.delete_task(task_id):
    await retry_on_flood(query.message.edit_text)("<i>Your Task Cancelled !</i>")
  else:
    await retry_on_flood(query.answer)(" Task Not Found ", show_alert=True)
    await retry_on_flood(query.message.delete)()


@Bot.on_callback_query(filters.regex("^scg") & is_auth_query())
async def query_group_handler(_, query):
  """This Is Group Handler Of Callback Data"""
  if query.data not in _storage:
    await igrone_error(query.answer)("This is an old button, please redo the search", show_alert=True)
    return

  manga_card = _storage[query.data]

  group_raw = {}
  for chapter in manga_card.chapters:
    group_name = chapter.get("group_name", "Unknown").lower()
    if not group_name: 
      group_name = "Unknown"

    group_raw.setdefault(group_name, []).append(chapter)

  button = []
  for group_name, chapters in group_raw.items():
    c = f"sfc:{manga_card.webs.sf}:{hash(chapters[0]['url'])}:{hash(chapters[-1]['url'])}"
    _storage[c] = (chapters, manga_card)
    button.append(InlineKeyboardButton(f"{group_name} [{len(chapters)}]", callback_data=c))

  button = split_list(button)
  button.insert(0, [InlineKeyboardButton(" 𝙲𝚑𝚘𝚘𝚜𝚎 𝚂𝚌𝚊𝚗𝚕𝚊𝚝𝚘𝚛 ", copy_text = "  𝗞𝗼𝗻𝗻𝗶𝗰𝗵𝗶𝘄𝗮 𝗦𝗲𝗻𝗽𝗮𝗶 , 𝗴𝗼-𝗿𝗶𝘆ō 𝗮𝗿𝗶𝗴𝗮𝘁ō 𝗴𝗼𝘇𝗮𝗶𝗺𝗮𝘀𝘂..  ")])

  subs_bool = await database.get_subs(str(query.from_user.id), manga_card.url, manga_card.webs.sf)
  subs_bool = True if subs_bool else False

  c = f"pg:{manga_card.webs.sf}:{hash(manga_card.chapters[-1]['url'])}:n:"
  pagination[c] = (manga_card, [])
  button.append([InlineKeyboardButton("♚ ᴄʜᴀᴘᴛᴇʀꜱ ♚", callback_data=c)])

  sdata = Subscribes(
    manga_url=manga_card.url,
    manga_title=manga_card.title,
    webs=manga_card.webs.sf,
    lastest_chapter=manga_card.chapters[0]['title'] if manga_card.chapters else ""
  )
  c = f"subs:{hash(manga_card.url)}"
  subscribes[c] = sdata

  if manga_card.webs.sf != "dj":
    if subs_bool:
      button.append([InlineKeyboardButton("✘ ᴜɴsᴜʙsᴄʀɪʙᴇ ✘", callback_data=c)])
    else:
      button.append([InlineKeyboardButton("✓ sᴜʙsᴄʀɪʙᴇ ✓", callback_data=c)])

  button.append([
    InlineKeyboardButton("⇦ 𝗕𝗔𝗖𝗞", callback_data=f"plugin_{manga_card.webs.sf}"),
    InlineKeyboardButton("▏𝗖𝗟𝗢𝗦𝗘▕", callback_data="kclose")
  ])
  await retry_on_flood(query.edit_message_reply_markup)(InlineKeyboardMarkup(button))


@Bot.on_callback_query(filters.regex("^sfc") & is_auth_query())
async def scg_group_handler(_, query):
  """This Is Group Handler Of Callback Data"""
  if query.data not in _storage:
    await igrone_error(query.answer)("This is an old button, please redo the search", show_alert=True)
    return

  chapters, manga_card =  _storage[query.data]
  subs_bool = await database.get_subs(str(query.from_user.id), manga_card.url, manga_card.webs.sf)
  subs_bool = True if subs_bool else False

  button = _create_chapters_button_(
    chapters=chapters, page=1, subs_bool=True,
    manga_card=manga_card, mode=True
  )
  if not button:
    return await igrone_error(query.answer)("No chapters found", show_alert=True)

  await igrone_error(query.answer)()
  await retry_on_flood(query.edit_message_reply_markup)(InlineKeyboardMarkup(button))

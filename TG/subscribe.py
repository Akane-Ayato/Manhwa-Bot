from bot import Bot, Vars, logger
from Tools.db import database, get_episode_number
from TG.storage import igrone_error, subscribes, filters
import random
from TG.storage import retry_on_flood, check_get_web, is_auth_query, searchs
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from Tools.base import MangaCard, Subscribes


@Bot.on_callback_query(filters.regex("^subs") & is_auth_query())
async def subs_handler(client, query):
  """This Is Subscribe Handler Of Callback Data"""
  if query.data not in subscribes:
    await retry_on_flood(query.answer)("This is an old button, please redo the search")
    return

  data_class_ = subscribes[query.data]

  reply_markup = query.message.reply_markup
  button = reply_markup.inline_keyboard
  button_postion = -2 #-3 if len(button) >= 3 else -2

  if await database.get_subs(str(query.from_user.id), data_class_.manga_url, data_class_.webs):
    check = await database.delete_sub(str(query.from_user.id), data_class_.manga_url, data_class_.webs)

    button[button_postion] = [InlineKeyboardButton("✓ sᴜʙsᴄʀɪʙᴇ ✓", callback_data=query.data)] 
    await igrone_error(query.answer)(" Comic Unsubscribed ")
  else:
    check = await database.add_sub(str(query.from_user.id), data_class_, data_class_.webs)
    if check is not True:
      await retry_on_flood(query.answer)("Error at Adding Subscribe")
      return

    button[button_postion] = [InlineKeyboardButton("✘ ᴜɴsᴜʙsᴄʀɪʙᴇ ✘", callback_data=query.data)]

    await igrone_error(query.answer)(" Comic Subscribed ")

  try:
    await retry_on_flood(query.edit_message_reply_markup)(InlineKeyboardMarkup(button))
  except Exception:
    rand_pic = random.choice(Vars.PICS)
    try:
      await retry_on_flood(query.edit_message_media)(
        InputMediaPhoto(rand_pic, caption=query.message.caption),
        reply_markup=button
      )
    except Exception as er:
      logger.error(f" Near 48 at subscribe.py {er}")




async def isubs_handle(process, page, user_id):
  """This Is Subscribe Handler Of Callback Data"""
  def iterate_subs(subs, page=1):
    try:
      return subs[(page - 1) * 10:page * 10] if page != 1 else subs[:10]
    except Exception:
      return None

  await database.ensure_user(user_id)
  page = int(page)

  all_manga_subs = await database.get_subs(user_id)

  if not all_manga_subs:
    await retry_on_flood(process)(" ` You Have No Subscribe Any Manga `")
    return

  if all_manga_subs is True:
    await retry_on_flood(process)("` You Have No Subscribe Any Manga `")
    return

  button = []
  manga_subs = iterate_subs(all_manga_subs, page=int(page))
  if not manga_subs:
    return button

  for data in manga_subs:
    web = check_get_web(data['url'])
    if not web:
      continue

    webs_name = type(web).__name__
    webs_name = webs_name.replace("Webs", "")

    manga_card = MangaCard.from_dict(data) # Convert to MangaCard Class Object
    manga_card.webs = web
    manga_card.chapters = []

    c = f"chs|{web.sf}{hash(manga_card.url)}"
    searchs[c] = manga_card

    lastest_ep = get_episode_number(data.get('lastest_chapter', 'None'))
    if lastest_ep is None:
      lastest_ep = data.get('lastest_chapter', 'None')

    button.append([
      InlineKeyboardButton(f"{data['title']} [{webs_name}]", callback_data=c),
      InlineKeyboardButton(
        f"{lastest_ep}", 
        callback_data="just_kidding",
      )
    ])

  arrow = []
  if iterate_subs(all_manga_subs, page=int(page - 1)):
    arrow.append(InlineKeyboardButton("<<", callback_data=f"isubs:{page-1}"))
  if iterate_subs(all_manga_subs, page=int(page - 2)):
    arrow.append(InlineKeyboardButton("<2x", callback_data=f"isubs:{page-2}"))

  if iterate_subs(all_manga_subs, page=int(page + 1)):
    arrow.append(InlineKeyboardButton(">>", callback_data=f"isubs:{page+1}"))
  if iterate_subs(all_manga_subs, page=int(page + 2)):
    arrow.append(InlineKeyboardButton("2x>", callback_data=f"isubs:{page+2}"))

  button.append(arrow)
  button.append([
    InlineKeyboardButton("✵ Clean All Subscribe ✵", callback_data="pqi_clean_all_subs"),
    InlineKeyboardButton("✵ Refresh ✵", callback_data=f"isubs:{page}")
  ])

  button.append([
      InlineKeyboardButton("◊ ǫᴜᴇᴜᴇ ◊", callback_data="refresh_queue"),
      InlineKeyboardButton("▏𝗖𝗟𝗢𝗦𝗘▕", callback_data="kclose")
  ])

  return button


@Bot.on_message(filters.command(["subs", "subscribes"]))
async def isubs_cmds(_, message):
  """This Is Subscribe Handler Of Callback Data"""
  sts = await retry_on_flood(message.reply_text)("<code>Processing...</code>", quote=True)
  user_id = str(message.from_user.id)
  await database.ensure_user(user_id)

  button = await isubs_handle(
    process=sts.edit_text, 
    page=1, 
    user_id=user_id
  )
  if not button:
    return await igrone_error(sts.edit_text)(" ` You Have No Subscribe Any Manga `")

  try:
    await retry_on_flood(sts.edit_media)(
      InputMediaPhoto(random.choice(Vars.PICS), caption="<i>Your Subs ..</i>"),
      reply_markup=InlineKeyboardMarkup(button) if button else None
    )
  except Exception:
    await retry_on_flood(message.reply_photo)(
      photo=random.choice(Vars.PICS),
      caption="<i>Your Subs ..</i>",
      reply_markup=InlineKeyboardMarkup(button) if button else None,
      quote=True,
    )


@Bot.on_callback_query(filters.regex("^isubs") & is_auth_query())
async def isubs_callback(client, query):
  """This Is Subscribe Handler Of Callback Data"""
  try:
    page = query.data.split(":")[1]
  except Exception:
    page = 1

  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)
  button =  await isubs_handle(
    process=query.answer,
    page=page,
    user_id=user_id
  )
  if not button:
     return await igrone_error(query.answer)("You Have No Subscribe Any Manga")

  await igrone_error(query.answer)()
  try:
    await retry_on_flood(query.edit_message_media)(
      InputMediaPhoto(random.choice(Vars.PICS), caption=f"<i>Your Subscribe of Page {page} ...</i>"),
      reply_markup=InlineKeyboardMarkup(button)
    )
  except Exception:
    await igrone_error(query.edit_message_reply_markup)(InlineKeyboardMarkup(button))


@Bot.on_callback_query(filters.regex("^pqi_clean_all_subs$") & is_auth_query())
async def _clean_all_subs_handler(client, query):
  """This Is Clean All Subs Handler Of Callback Data"""
  user_id = str(query.from_user.id)
  if not await database.get_subs(user_id):
    return await query.answer("You Have No Subscribe Any Manga", show_alert=True)

  await database.delete_sub(user_id)
  await query.answer("All Subs Deleted", show_alert=True)
  await igrone_error(query.message.reply_to_message.delete)()
  try: 
    await retry_on_flood(query.message.delete)()
  except Exception: 
    pass
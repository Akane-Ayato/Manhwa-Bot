from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from bot import Bot, Vars, logger
from Tools.db import database
from .storage import igrone_error, retry_on_flood
import random
from Tools.compat import forwarded_chat
from Tools.listen import ListenerTimeout as TimeoutError, install as _install_listen
_install_listen(Bot)  # adds Client.listen on libraries without pyromod (kurigram); no-op on pyrofork

users_txt = """

<b><blockquote expandable>➥ File Name: <code>{file_name}</code><code>[{len}]</code>
➥ Caption: <code>{caption}</code>
➥ Thumbnail: <code>{thumb}</code>
➥ File Type: <code>{type}</code>
➥ PDF Password: <code>{password}</code>
➥ Megre Size: <code>{megre}</code>
➥ Regex/Zfill: <code>{regex}</code>
➥ Banner 1: <code>{banner1}</code>
➥ Banner 2: <code>{banner2}</code>
➥ Dump Channel: <code>{dump}</code>
➥ Compression Quality: <code>{compress}</code>
➥ HyperLink: <code>{hyper}</code>
➥ Update Channel : <code>{update_c}</code>
➥ Update Button: <code>{update_b}</code>
➥ Update Text: <code>{update_t}</code>
➥ Update Sticker: <code>{update_s}</code>
➥ Channel Sticker: <code>{target_s}</code>
➥ Before Post: <code>{before_post}</code>
➥ After Post: <code>{after_post}</code>
➥ Auto Post: <code>{auto_post}</code></blockquote></b>"""


info_data_text = {
  "caption": {
    "type": "Caption",

    "text": """
<b>◈ Send Caption ◈ 

<u>Note:</u> <blockquote>Use HTML Tags For Bold, Italic,etc</blockquote>

<u>Params:</u>
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number
➥ <code>{file_name}</code>: File Name</b>

➥ /cancel: To Cancel The Process""",

    "caption": """
<b><blockquote>Caption</blockquote>

<blockquote expandable>Format:
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number
➥ <code>{file_name}</code>: File Name</blockquote>

<blockquote>➥ Your Value: <code>{value}</code></blockquote></b>"""
  },

  "dump": {
    "type": "Dump Channel",
    "text": """
<b>◈ Send Dump Channel ◈ 

➥ /cancel: To Cancel The Process

<u>Note:</u> <blockquote>You Can Send Username(without @) or Channel Id or Forward Message from Channel.. </blockquote></b>"""
  },

  "megre": {
    "type": "Megre Size",
    "text": """
"<b>◈ Send Megre Size ◈ 

➥ /cancel: To Cancel The Process

<u>Note:</u> <blockquote>It's Number For Megre. i.e 2, 3 ,4 ,5,etc </blockquote></b>"""
  },

  "password": {
    "type": "Password",
    "text": "<b>◈ Send Password ◈ \n\n➥ /cancel: To Cancel Process \n\n<u>Note:</u> <blockquote>It's Password For PDF.</blockquote></b>"
  },

  "hyper": {
    "type": "HyperLink",
    "text": "<b>◈ Send HyperLink ◈ \n\n➥ /cancel: To cancel process \n\n<u>Note:</u> <blockquote>It's HyperLink For PDF.</blockquote></b>"
  },

  "update_c": {
    "type": "Update Channel",
    "text": "<b>◈ Send Update Channel ◈ \n\n➥ /cancel: To cancel process\n\n<u>Note:</u> <blockquote>You Can Send Username(without @) or Channel Id or Forward Message from Channel.. </blockquote></b>"
  },

  "update_t": {
    "type": "Update Text",
    "text": """<b>◈ Send Update Text ◈ 

<u>Note:</u> <blockquote>It's Update Text For Update Channel. </blockquote>

<u>Params:</u>
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number
➥ <code>{channel_title}</code>: Channel Title
➥ <code>{channel_link}</code>: To Redirect to Channel
➥ <code>{read_link}</code>: To Redirect to Read Link

<u>* Donot forget to use <: from and >: for redirecting to links, See Example Below *</u>

<u>Example</u>
<code>{channel_title}

➥ < Cʜᴀᴘᴛᴇʀ {chapter_num} >{read_link} Uᴘᴅᴀᴛᴇᴅ
➥ < Rᴇᴀᴅ Nᴏᴡ >{channel_link} </code></b>""",

    "caption": """
<b><blockquote>➥ Update Text</blockquote>

<blockquote expandable><u>Params:</u>
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number
➥ <code>{channel_title}</code>: Channel Title
➥ <code>{channel_link}</code>: To Redirect to Channel
➥ <code>{read_link}</code>: To Redirect to Read Link

<u>* Donot forget to use <: from and >: for redirecting to links, See Example Below *</u></blockquote>

<blockquote>➥ Your Value: <code>{value}</code></blockquote></b>
"""
  },

  "before_post": {
    "type": "Before Post",
    "text": """<b>◈ Send Before Post ◈

<u>Note:</u> <blockquote>Text (HTML allowed) or a sticker. It is posted into the channel right BEFORE every chapter file.</blockquote>

<u>Params:</u>
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number

➥ /cancel: To Cancel The Process</b>"""
  },

  "after_post": {
    "type": "After Post",
    "text": """<b>◈ Send After Post ◈

<u>Note:</u> <blockquote>Text (HTML allowed) or a sticker. It is posted into the channel right AFTER every chapter file.</blockquote>

<u>Params:</u>
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number

➥ /cancel: To Cancel The Process</b>"""
  },

  "update_s": {
    "type": "Update Sticker",
    "text": "<b>◈ Send Update Sticker ◈ \n<u>Note:</u> <blockquote>It's Update Sticker For Update Channel.</blockquote></b>"
  },

  "target_s": {
    "type": "Channel Sticker",
    "text": "<b>◈ Send Target Channel Sticker ◈ \n<u>Note:</u> <blockquote>It's Upload Sticker when Updating in Target channel. You Can Send Username(without @) or Channel Id or Forward Message from Channel.. </blockquote></b>"
  },


  "file_name": {
    "type": "File Name",
    "text": "<b>◈ Send File Name ◈ \n\n<u><i>Params:</u></i>\n➥<code>{manga_title}</code>: Manga Name \n➥ <code>{chapter_num}</code>: Chapter Number\n\n➥/cancel: To cancel process</b>",

    "caption": """
<b><blockquote>➥ File Name </blockquote>

<blockquote expandable><u><i>Params:</u>
➥ <code>{manga_title}</code>: Manga Name 
➥ <code>{chapter_num}</code>: Chapter Number</blockquote>

<blockquote>➥ Your File Name: <code>{value}</code>
➥ Your File Name Len: <code>{flen}</code></blockquote></b>"""
  },


  "update_b": {
    "type": "Update Button",
    "text": """
<b>➥ ◈ Send Update Button ◈

➥ <u>Note:</u> <blockquote>It's Update Button For Update Channel.</blockquote>

➥ <u>Params:</u>
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number
➥ <code>{channel_title}</code>: Channel Title
➥ <code>{channel_link}</code>: To Redirect to Channel
➥ <code>{read_link}</code>: To Redirect to Read Link
➥ <code> | </code>: To Seperate Buttons
➥ <code> - </code>: To Seperate Button Text and Link

➥ <u>Example</u>

<pre>Join Channel {channel_title} - {channel_link} | {chapter_num} - {read_link}
Next Line Button Text - http://www.example3.com/
Next Line Another Button Text - http://www.example3.com/</pre>

➥ Format:- <code>Text - Url </code>
➥ Do not add any text in the URL part. If you do, the bot will ignore it.
➥ /cancel :- To Cancel Process </b>""",

    "caption": """
<b><blockquote>➥ Update Text</blockquote>

<blockquote expandable><u>Params:</u>
➥ <code>{manga_title}</code>: Manga Name
➥ <code>{chapter_num}</code>: Chapter Number
➥ <code>{channel_title}</code>: Channel Title
➥ <code>{channel_link}</code>: To Redirect to Channel
➥ <code>{read_link}</code>: To Redirect to Read Link
➥ <code> | </code>: To Seperate Buttons
➥ <code> - </code>: To Seperate Button Text and Link</blockquote>

<blockquote>➥ Your Value: <code>{value}</code></blockquote></b>"""
  }
}


simple_caption_txt_format = "<blockquote expandable><b>➥ {type}\n\n➥ Your Value: {value}</b></blockquote>"



def _short(value) -> str:
  if not value:
    return "None"
  return "Sticker" if str(value).startswith("sticker:") else (str(value)[:40] + ("..." if len(str(value)) > 40 else ""))


async def get_user_txt(user_id):
  user_id = str(user_id)
  uts = await database.get_settings(user_id)

  thumbnali = uts.get("thumb", None)

  if thumbnali:
    thumb = thumbnali if thumbnali.startswith("http") else "True"
    thumb = "Constant" if thumbnali == "constant" else thumbnali
  else:
    thumb = thumbnali

  banner1 = uts.get("banner1", None)
  banner2 = uts.get("banner2", None)

  if banner1:
    banner1 = banner1 if banner1.startswith("http") else "True"

  if banner2:
    banner2 = banner2 if banner2.startswith("http") else "True"

  update_sticker = uts.get("update_s", None)
  update_sticker = "True" if update_sticker else "False"
  target_s = uts.get("target_s", None)
  target_s = "True" if target_s else "False"

  txt = users_txt.format(
    id=user_id,
    file_name=uts.get("file_name", "None"),
    caption=uts.get("caption", "None"),
    thumb=thumb,
    banner1=banner1,
    banner2=banner2,
    dump=uts.get("dump", "None"),
    type=uts.get("type", "None"),
    megre=uts.get("megre", "None"),
    regex=uts.get("regex", "None"),
    len=uts.get("file_name_len", "None"),
    password=uts.get("password", "None"),
    compress=uts.get("compress", "None"),
    hyper=uts.get("hyper", "None"),
    update_c=uts.get("update_c", "None"),
    update_t=uts.get("update_t", "None"),
    update_s=update_sticker,
    target_s=target_s,
    update_b=uts.get("update_b", "None"),
    before_post=_short(uts.get("before_post")),
    after_post=_short(uts.get("after_post")),
    auto_post="ON" if uts.get("auto_upload", True) is not False else "OFF"
  )

  return txt


caption_sample_text = """<b><blockquote>➥ User Setting Panel</blockquote>

<blockquote expandable>➥ ID: <code>{user_id}</code>
➥ Full Name: <code>{full_name}</code>
➥ DC ID: <code>{dc_id}</code></blockquote></b>"""


async def main_settings(_, message_query, user_id):
  await database.ensure_user(user_id)

  settings = await database.get_settings(user_id)

  thumbnali = settings.get("thumb", None)
  try: 
    user_info = await Bot.get_users(user_id)
  except Exception:
    user_info = None

  caption_txt = caption_sample_text.format(
    user_id=user_id,
    full_name=user_info.first_name if user_info and not isinstance(user_info, list) else "None",
    dc_id=user_info.dc_id if user_info and not isinstance(user_info, list) else "None"
  )

  user_panel_text = await get_user_txt(user_id)
  if len(caption_txt + user_panel_text) < 1024:
    caption_txt = caption_txt + user_panel_text
  elif len(user_panel_text) < 1024:
    caption_txt = user_panel_text

  auto_on = settings.get("auto_upload", True) is not False
  auto_txt = 'ON ✓' if auto_on else 'OFF ⊘'
  button = [
    [
      InlineKeyboardButton(f" Auto Post: {auto_txt} ", callback_data="autoup_toggle"),
    ],
    [
      InlineKeyboardButton(" Auto Update Channels ", callback_data="auto_channel"),
    ],
    [
      InlineKeyboardButton(" Banner ", callback_data="ubn"),
      InlineKeyboardButton(" Caption ", callback_data="sinfo_caption"),
    ],
    [
      InlineKeyboardButton(" Channel Stickers ", callback_data="sinfo_target_s"),
      InlineKeyboardButton(" Compress ", callback_data="u_compress"),
    ],
    [
      InlineKeyboardButton(" File Name ", callback_data="sinfo_flen"),
      InlineKeyboardButton(" File Type ", callback_data="u_file_type"),
    ],
    [
      InlineKeyboardButton(" Auto Upload Channels ", callback_data="target_channel"),
    ],
    [
      InlineKeyboardButton(" Hyper Link ", callback_data="sinfo_hyper"),
      InlineKeyboardButton(" Merge Size ", callback_data="sinfo_megre"),
    ],
    [
      InlineKeyboardButton(" Password ", callback_data="sinfo_password"),
      InlineKeyboardButton(" Regex ", callback_data="uregex"),
    ],
    [
      InlineKeyboardButton(" Thumbnail ", callback_data="uth"),
      InlineKeyboardButton(" Update Channel ", callback_data="sinfo_update_c"),
    ],
    [
      InlineKeyboardButton(" Dump Channel ", callback_data="sinfo_dump"),
    ],
    [
      InlineKeyboardButton(" Update Text ", callback_data="sinfo_update_t"),
      InlineKeyboardButton(" Update Sticker ", callback_data="sinfo_update_s"),
    ],
    [
      InlineKeyboardButton(" Update Button ", callback_data="sinfo_update_b"),
    ],
    [
      InlineKeyboardButton(" Before Post ", callback_data="sinfo_before_post"),
      InlineKeyboardButton(" After Post ", callback_data="sinfo_after_post"),
    ],
    [
      InlineKeyboardButton(" Test Settings ", callback_data="stest"),
    ],
    [
      InlineKeyboardButton("✧ 𝘏𝘰𝘮𝘦 ✧", callback_data="home"),
      InlineKeyboardButton("✵ 𝘊𝘭𝘰𝘴𝘦 ✵", callback_data="close")
    ]
  ]

  if not thumbnali or thumbnali == "constant":
    thumbnali = random.choice(Vars.PICS)

  try:
    await retry_on_flood(message_query.edit_media)(
      InputMediaPhoto(thumbnali, caption=caption_txt),
      reply_markup=InlineKeyboardMarkup(button)
    )
  except Exception:
    await retry_on_flood(message_query.edit_media)(
      InputMediaPhoto(Vars.PICS[0], caption=caption_txt),
      reply_markup=InlineKeyboardMarkup(button),
    )



@Bot.on_callback_query(filters.regex("^autoup_toggle$"))
async def auto_upload_toggle(client, query):
  uid = query.from_user.id
  await database.ensure_user(uid)
  settings = await database.get_settings(uid)
  new = settings.get("auto_upload", True) is False      # off -> on, on -> off
  await database.set_value(uid, "auto_upload", new)
  await query.answer("Auto upload " + ("ON" if new else "OFF"))
  await main_settings(client, query.message, uid)


@Bot.on_message(filters.command(["settings", "us", "user_setting", "user_panel"]))
async def userxsettings(client, message):
  if Vars.IS_PRIVATE:
    if message.chat.id not in Vars.ADMINS:
      return await message.reply("<code>You cannot use me baby </code>")

  sts = await retry_on_flood(message.reply)("<code>Processing...</code>", quote=True)
  await database.ensure_user(message.from_user.id)
  try:
    await main_settings(client, sts, message.from_user.id)
    #await retry_on_flood(sts.delete)()
  except Exception as err:
    logger.exception(err)
    await retry_on_flood(sts.edit)(err)



@Bot.on_callback_query(filters.regex("^mus$"))
async def main_user_panel(_, query):
  await igrone_error(query.answer)()
  await database.ensure_user(query.from_user.id)
  await main_settings(_, query.message, query.from_user.id)



@Bot.on_callback_query(filters.regex("^sinfo"))
async def user_settings(_, query):
  type = query.data.split("_", 1)[-1]
  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)

  usettings = await database.get_settings(user_id)
  value_type = usettings.get(type, None)
  button = [
    [
      InlineKeyboardButton(" 𝘚𝘦𝘵 / 𝘊𝘩𝘢𝘯𝘨𝘦 ", callback_data=f"sset_{type}"),
      InlineKeyboardButton(" 𝘋𝘦𝘭𝘦𝘵𝘦 ", callback_data=f"sdelete_{type}")
    ],
    [
      InlineKeyboardButton(" ⇦ 𝘉𝘢𝘤𝘬 ", callback_data="mus"),
      InlineKeyboardButton(" ✵ 𝘊𝘭𝘰𝘴𝘦 ✵ ", callback_data="close")
    ]
  ]

  if type in ("before_post", "after_post") and value_type and str(value_type).startswith("sticker:"):
    value_type = "Sticker"

  if type in ("update_s", "target_s"):
    value_type = "True" if value_type else "None"

    stickers = usettings.get(type, None)
    if stickers:
      await retry_on_flood(query.message.reply_sticker)(
        stickers,
        reply_markup=InlineKeyboardMarkup([
          [InlineKeyboardButton("✵ 𝘊𝘭𝘰𝘴𝘦 ✵", callback_data="close")]
        ])
      )

  elif type in ("file_name", "flen", "file_name_len"):
    type = "file_name"
    value_type = usettings.get("file_name", "None")

    button = [
      [
        InlineKeyboardButton(" 𝘚𝘦𝘵 / 𝘊𝘩𝘢𝘯𝘨𝘦 ", callback_data="sset_file_name"),
        InlineKeyboardButton(" 𝘋𝘦𝘭𝘦𝘵𝘦 ", callback_data="sdelete_file_name")
      ],
      [
        InlineKeyboardButton(" 𝘚𝘦𝘵 / 𝘊𝘩𝘢𝘯𝘨𝘦  𝘓𝘦𝘯 ", callback_data="sset_file_name_len"),
        InlineKeyboardButton(" 𝘋𝘦𝘭𝘦𝘵𝘦 𝘓𝘦𝘯 ", callback_data="sdelete_file_name_len")
      ], 
      [
        InlineKeyboardButton(" ⇦ 𝘉𝘢𝘤𝘬 ", callback_data="mus"),
        InlineKeyboardButton(" ✵ 𝘊𝘭𝘰𝘴𝘦 ✵ ", callback_data="close")
      ]
    ]
  else:
    button = [
      [
        InlineKeyboardButton(" 𝘚𝘦𝘵 / 𝘊𝘩𝘢𝘯𝘨𝘦 ", callback_data=f"sset_{type}"),
        InlineKeyboardButton(" 𝘋𝘦𝘭𝘦𝘵𝘦 ", callback_data=f"sdelete_{type}")
      ],
      [
        InlineKeyboardButton(" ⇦ 𝘉𝘢𝘤𝘬 ", callback_data="mus"),
        InlineKeyboardButton(" ✵ 𝘊𝘭𝘰𝘴𝘦 ✵ ", callback_data="close")
      ]
    ]


  caption_txt = info_data_text.get(type, {}).get("caption", None)
  if not caption_txt:
    caption_txt = simple_caption_txt_format

  flen = usettings.get("file_name_len", "None")
  caption_txt = caption_txt.replace("{type}", info_data_text.get(type, {}).get('type', 'Unknown'))
  caption_txt = caption_txt.replace("{value}", str(value_type))
  caption_txt = caption_txt.replace("{flen}", str(flen))

  if len(caption_txt) > 1024:
    caption_txt = simple_caption_txt_format
    caption_txt = caption_txt.replace("{type}", info_data_text.get(type, {}).get('type', 'Unknown'))
    caption_txt = caption_txt.replace("{value}", str(value_type))


  await igrone_error(query.answer)()
  try:
    await retry_on_flood(query.edit_message_media)(
      InputMediaPhoto(random.choice(Vars.PICS), caption_txt),
      reply_markup=InlineKeyboardMarkup(button)
    )
  except Exception:
    await retry_on_flood(query.edit_message_reply_markup)(InlineKeyboardMarkup(button))


@Bot.on_callback_query(filters.regex("^sset"))
async def user_settings_set(_, query):
  type = query.data.removeprefix("sset_")
  user_id = str(query.from_user.id)

  await database.ensure_user(user_id)

  #usettings = await database.get_settings(user_id)

  try:
    if type == "file_name_len":
      caption_txt = "<b>◈ Send File Name Len ◈\n Example: 15, 20, 50</b>"
    else:
      caption_txt = info_data_text[type].get("text", "<i> ➥ Text Not Found !, Report to Admins and send /cancel </i>")

    await retry_on_flood(query.edit_message_caption)(caption_txt)

    call_ = await _.listen(user_id=int(user_id), timeout=80, filters=filters.text | filters.forwarded | filters.sticker)
    if call_.text == "/cancel":
      await retry_on_flood(query.answer)("Sucessfully Cancelled")

    elif type in ("dump", "update_c", "file_name_len"):
      if forwarded_chat(call_):
        await database.set_value(user_id, type, forwarded_chat(call_).id)

      elif call_.text:
        try: 
          _value_ = int(call_.text)
        except Exception: 
          _value_ = call_.text

        await database.set_value(user_id, type, _value_)

    elif type in ("before_post", "after_post"):
      if call_.sticker:
        await database.set_value(user_id, type, "sticker:" + call_.sticker.file_id)
      elif call_.text:
        await database.set_value(user_id, type, call_.text.html if hasattr(call_.text, "html") else call_.text)

    elif type in ("update_s", "target_s"):
      if call_.sticker:
         await database.set_value(user_id, type, call_.sticker.file_id)
         await igrone_error(query.answer)("✦ Sucessfully Added ✦")

      else:
        await retry_on_flood(query.message.reply_text)("◈ ᴛʜɪs ɪs ɴᴏᴛ ᴀ ᴠᴀʟɪᴅ sᴛɪᴄᴋᴇʀ ◈")

    else:
      await database.set_value(user_id, type, call_.text)

    await igrone_error(call_.delete)()

  except TimeoutError:
    await igrone_error(query.answer)("◈ ᴛɪᴍᴇᴏᴜᴛ ◈")
  except Exception as err:
    await igrone_error(query.answer)(f"◈ {err} ◈")

  await igrone_error(query.answer)()
  await user_settings(_, query)




@Bot.on_callback_query(filters.regex("^sdelete"))
async def user_settings_delete(_, query):
  type = query.data.removeprefix("sdelete_")
  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)

  usettings = await database.get_settings(user_id)

  if usettings.get(type, None) is not None:
    await database.delete_value(user_id, type)

    await retry_on_flood(query.answer)("Sucessfully Deleted")
    await user_settings(_, query)

  else:
    await retry_on_flood(query.answer)(
      "◈ 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! ◈", show_alert=True
    )



@Bot.on_callback_query(filters.regex("^uth"))
async def thumb_handler(_, query):
  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)

  usettings = await database.get_settings(user_id)
  thumbnali = usettings.get("thumb", None)

  if query.data == "uth_constant":
    await database.set_value(user_id, "thumb", "constant")

    await retry_on_flood(query.answer)("✦ Sucessfully Added ✦")

  elif query.data == "uth_change":
    await retry_on_flood(query.edit_message_caption)("<b>◈ Send Thumbnail ◈\n<u>Note:</u> <blockquote>Links, Images, or Base64 (data:image/...)</blockquote></b>")

    try:
      c = await _.listen(user_id=int(user_id), timeout=60)
      v = c.photo or c.document or None
      if v:
        t = v.file_id
        await database.set_value(user_id, "thumb", t)

      else:
        t = c.text
        if t.startswith("http") or t.startswith("data:image") or t.startswith("/9j") or t.startswith("iVBOR"):
          await database.set_value(user_id, "thumb", t)

        else:
          await igrone_error(query.answer)("◈ Invalid ◈")

      await igrone_error(c.delete)()
      await igrone_error(query.answer)("✦ Added ✦")

    except TimeoutError:
      await igrone_error(query.answer)("◈ Timeout ◈", True)

    except Exception as e:
      await igrone_error(query.answer)(f"◈ {e} ◈", True)


  elif query.data == "uth_delete":
    if thumbnali:
      await database.delete_value(user_id, "thumb")

    else:
      await igrone_error(query.answer)("◈ Not Set ◈")


  await igrone_error(query.answer)()
  usettings = await database.get_settings(user_id)

  t = usettings.get("thumb", None)
  tt = 'Constant' if t and str(t).lower() == 'constant' else 'True' if t else 'None'

  txt = simple_caption_txt_format.replace("{type}", "Thumbnail").replace("{value}", tt)
  txt += "\n\n<blockquote><b>➥ Constant:- MANGA POSTER AS THUMB</b></blockquote>"

  if not t or str(t).lower() == "constant":
    t = random.choice(Vars.PICS)

  b = [[InlineKeyboardButton(" 𝘚𝘦𝘵 / 𝘊𝘩𝘢𝘯𝘨𝘦 ", callback_data="uth_change"),InlineKeyboardButton(" 𝘋𝘦𝘭𝘦𝘵𝘦 ", callback_data="uth_delete")],[InlineKeyboardButton(" 𝘊𝘰𝘯𝘴𝘵𝘢𝘯𝘵 ", callback_data="uth_constant")],[InlineKeyboardButton(" ⇦ 𝘉𝘢𝘤𝘬 ", callback_data="mus"),InlineKeyboardButton(" ✵ 𝘊𝘭𝘰𝘴𝘦 ✵ ", callback_data="close")]]

  try:
    if isinstance(t, str) and (t.startswith("data:image") or t.startswith("/9j") or t.startswith("iVBOR")):
      import base64
      from io import BytesIO

      b64 = t.split(",", 1)[1] if t.startswith("data:") else t
      img = BytesIO(base64.b64decode(b64))

      img.name = "thumb.jpg"

      t = img
    await retry_on_flood(query.edit_message_media)(InputMediaPhoto(t, txt), InlineKeyboardMarkup(b))
  except Exception:
    await retry_on_flood(query.edit_message_media)(InputMediaPhoto(random.choice(Vars.PICS), txt), InlineKeyboardMarkup(b))

  await igrone_error(query.answer)()



@Bot.on_callback_query(filters.regex("^ubn"))
async def banner_handler(_, query):
  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)

  uts = await database.get_settings(user_id)
  banner1 = uts.get("banner1", None)
  banner2 = uts.get("banner2", None)

  if query.data.startswith("ubn_set"):
    s = ""
    await retry_on_flood(query.edit_message_media)(InputMediaPhoto(random.choice(Vars.PICS), "<b>◈ Send Banner ◈\n<u>Note:</u> <blockquote>URL (http...), Image, or Base64 (data:image/...)</blockquote></b>"))
    try:
      c = await _.listen(user_id=int(user_id), timeout=60)
      v = c.photo or c.document or None
      if v:
        s = c.photo.file_id if c.photo else c.document.file_id
      else:
        s = c.text
        u = s.startswith("http")
        b = s.startswith("data:image") or s.startswith("/9j") or s.startswith("iVBOR")
        if not u and not b:
          await retry_on_flood(query.answer)("◈ Invalid ◈")
          return

      if query.data == "ubn_set1":
        await database.set_value(user_id, "banner1", s)

      elif query.data == "ubn_set2":
        await database.set_value(user_id, "banner2", s)

      await retry_on_flood(c.delete)()

      await igrone_error(query.answer)("▸ Added ▸")

    except TimeoutError:
      await igrone_error(query.answer)("◈ Timeout ◈", True)

    except Exception as e:
      await igrone_error(query.answer)(f"◈ {e} ◈", True)



  elif query.data == "ubn_delete1":
    if banner1:
      await database.delete_value(user_id, "banner1")
    else:
      return await igrone_error(query.answer)("◈ Not Set ◈", True)


  elif query.data == "ubn_delete2":
    if banner2:
      await database.delete_value(user_id, "banner2")
    else:
      return await igrone_error(query.answer)("◈ Not Set ◈", True)


  elif (query.data == "ubn_show1" and not banner1) or (query.data == "ubn_show2" and not banner2):
    await igrone_error(query.answer)("◈ Not Set ◈", True)
    return 

  elif query.data.startswith("ubn_show"):
    p = banner1 if query.data == "ubn_show1" else banner2 if query.data == "ubn_show2" else None
    if not p:

      await igrone_error(query.answer)("◈ Error ◈", True)
      return

    try:
      if p.startswith("data:image") or p.startswith("/9j") or p.startswith("iVBOR"):
        import base64
        from io import BytesIO

        b6 = p.split(",", 1)[1] if p.startswith("data:") else p
        img = BytesIO(base64.b64decode(b6))

        img.name = "banner.jpg"
        await retry_on_flood(query.message.reply_photo)(img, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✵ 𝘊𝘭𝘰𝘴𝘦 ✵", callback_data="close")]]))
      else:
        await retry_on_flood(query.message.reply_photo)(p, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✵ 𝘊𝘭𝘰𝘴𝘦 ✵", callback_data="close")]]))

      await igrone_error(query.answer)()
      return

    except Exception:
      await igrone_error(query.answer)("◈ Error ◈", True)
      return

  uts = await database.get_settings(user_id)
  b1 = uts.get("banner1", None)
  b2 = uts.get("banner2", None)

  bs = b1 if b1 else b2
  b1t = "True" if b1 else "None"
  b2t = "True" if b2 else "None"
  if not bs:
    bs = random.choice(Vars.PICS)

  btn = [[InlineKeyboardButton(" 𝘚𝘦𝘵 / 𝘊𝘩𝘢𝘯𝘨𝘦 - 1 ", callback_data="ubn_set1"),InlineKeyboardButton(" 𝘋𝘦𝘭𝘦𝘵𝘦 - 𝟷 ", callback_data="ubn_delete1")],[InlineKeyboardButton(" 𝘚𝘩𝘰ᴡ 𝘉𝘢𝘯𝘯𝘦𝘳 - 1 ", callback_data="ubn_show1")],[InlineKeyboardButton(" 𝘚𝘦𝘵 / 𝘊𝘩𝘢𝘯𝘨𝘦 - 2 ", callback_data="ubn_set2"),InlineKeyboardButton("𝘋𝘦𝘭𝘦𝘵𝘦 - 𝟸", callback_data="ubn_delete2")],[InlineKeyboardButton(" 𝘚𝘩𝘰ᴡ 𝘉𝘢𝘯𝘯𝘦𝘳 - 2 ", callback_data="ubn_show2")],[InlineKeyboardButton(" ⇦ 𝘉𝘢𝘤𝘬 ", callback_data="mus"),InlineKeyboardButton(" ✵ 𝘊𝘭𝘰𝘴𝘦 ✵ ", callback_data="close")]]

  cap = f"<b><blockquote>Banner Setting</blockquote>\n\n<blockquote>➥ First: {b1t}\n➥ Last: {b2t}</blockquote></b>"

  await igrone_error(query.answer)()
  try:
    if isinstance(bs, str) and (bs.startswith("data:image") or bs.startswith("/9j") or bs.startswith("iVBOR")):

      import base64
      from io import BytesIO
      b6 = bs.split(",", 1)[1] if bs.startswith("data:") else bs
      img = BytesIO(base64.b64decode(b6))
      img.name = "banner.jpg"
      bs = img

    await retry_on_flood(query.edit_message_media)(InputMediaPhoto(bs, cap), InlineKeyboardMarkup(btn))
  except Exception:
    await retry_on_flood(query.edit_message_media)(InputMediaPhoto(random.choice(Vars.PICS), cap), InlineKeyboardMarkup(btn))




@Bot.on_callback_query(filters.regex("^u_file_type"))
async def type_handler(_, query):
  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)
  uts = await database.get_settings(user_id)

  if "type" not in uts:
    await database.set_value(user_id, "type", [])

  type = uts.get("type", [])

  button = [[]]
  if "PDF" in type:
    button[0].append(InlineKeyboardButton("❖ PDF ❖", callback_data="u_file_type_pdf"))
  else:
    button[0].append(InlineKeyboardButton("!PDF !", callback_data="u_file_type_pdf"))

  if "CBZ" in type:
    button[0].append(InlineKeyboardButton("▤ CBZ ▤", callback_data="u_file_type_cbz"))
  else:
    button[0].append(InlineKeyboardButton("!CBZ !", callback_data="u_file_type_cbz"))

  button.append([
    InlineKeyboardButton(" ⇦ 𝘉𝘢𝘤𝘬 ", callback_data="mus"),
    InlineKeyboardButton(" ✵ 𝘊𝘭𝘰𝘴𝘦 ✵ ", callback_data="close")
  ])

  if query.data == "u_file_type_pdf":
    if "PDF" in type:
      type.remove("PDF")

      button[0][0] = InlineKeyboardButton("!PDF !", callback_data="u_file_type_pdf")

    else:
      type.append("PDF")

      button[0][0] = InlineKeyboardButton("❖ PDF ❖", callback_data="u_file_type_pdf")

  elif query.data == "u_file_type_cbz":
    if "CBZ" in type:
      type.remove("CBZ")

      button[0][1] = InlineKeyboardButton("!CBZ !", callback_data="u_file_type_cbz")

    else:
      type.append("CBZ")

      button[0][1] = InlineKeyboardButton("▤ CBZ ▤", callback_data="u_file_type_cbz")

  await database.set_value(user_id, "type", type)
  uts = await database.get_settings(user_id)

  type = uts.get("type", [])
  caption_text = simple_caption_txt_format.replace("{type}", "File Type")
  caption_text = caption_text.replace("{value}", str(type))

  await retry_on_flood(query.edit_message_media)(
    media=InputMediaPhoto(random.choice(Vars.PICS), caption_text),
    reply_markup=InlineKeyboardMarkup(button)
  )

  await igrone_error(query.answer)()





@Bot.on_callback_query(filters.regex("^uregex"))
async def regex_handler(_, query):
  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)
  uts = await database.get_settings(user_id)

  regex = uts.get("regex", None)

  if query.data.startswith("uregex_set"):
    regex = query.data.split("_")[-1]

  elif query.data == "uregex_delete":
    if regex:
      regex = None

    else:
      await retry_on_flood(query.answer)("◈ 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! ◈")

  await database.set_value(user_id, "regex", regex)
  uts = await database.get_settings(user_id)
  regex = uts.get("regex", None)

  await igrone_error(query.answer)()
  button = [
    [
      InlineKeyboardButton(
        f"{'✓' if regex and str(regex) == str(i) else '' } {str(i)}", 
        callback_data=f"uregex_set_{i}") 
      for i in range(1, 5)
    ], 
    [
      InlineKeyboardButton("▏ᴅᴇʟᴇᴛᴇ▕", callback_data="uregex_delete"),
    ],
    [
      InlineKeyboardButton("⇦ 𝗕𝗔𝗖𝗞", callback_data="mus"),
      InlineKeyboardButton("▏𝗖𝗟𝗢𝗦𝗘▕", callback_data="close")
    ]
  ]

  caption_text = simple_caption_txt_format.replace("{type}", "Regex/Zfill")
  caption_text = caption_text.replace("{value}", str(regex))

  await retry_on_flood(query.edit_message_media)(
    media=InputMediaPhoto(random.choice(Vars.PICS), caption_text),
    reply_markup=InlineKeyboardMarkup(button)
  )



@Bot.on_callback_query(filters.regex("^u_compress"))
async def compress_handler(_, query):
  user_id = str(query.from_user.id)
  await database.ensure_user(user_id)

  uts = await database.get_settings(user_id)
  compress = uts.get("compress", None)

  def get_button(compress):
    compress = int(compress) if compress else 2
    button = []
    button = [
      InlineKeyboardButton(
        f"{'✓' if int(compress) == i else '' } {str(i)}",
        callback_data=f"u_compress_set_{i}"
      )
      for i in range(0, 105, 5)
    ]

    button = [button[x:x + 5] for x in range(0, len(button), 5)]

    button.append([
      InlineKeyboardButton("▏ᴅᴇʟᴇᴛᴇ▕", callback_data="u_compress_delete"),
    ])

    button.append([
      InlineKeyboardButton("⇦ 𝗕𝗔𝗖𝗞", callback_data="mus"),
      InlineKeyboardButton("▏𝗖𝗟𝗢𝗦𝗘▕", callback_data="close")
    ])

    return InlineKeyboardMarkup(button)


  if query.data.startswith("u_compress_set"):
    compress = query.data.split("_")[-1]

    await retry_on_flood(query.answer)(" Sucessfully Added ")

  elif query.data == "u_compress_delete":
    if compress:
      compress = None

      await retry_on_flood(query.answer)(" Sucessfully Deleted ")
    else:
      await retry_on_flood(query.answer)("◈ 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! ◈")

  await database.set_value(user_id, "compress", compress)
  compress = (await database.get_settings(user_id)).get("compress", None)

  caption_text = simple_caption_txt_format.replace("{type}", "Image Quality")
  caption_text = caption_text.replace("{value}", str(compress))
  caption_text += "\n\n<blockquote><b>➥ 100:- Real Quality \n➥ If the image quality is high, the image in the PDF will also be clear, and the file size will be larger. </b></blockquote>"
  await retry_on_flood(query.edit_message_media)(
    media=InputMediaPhoto(random.choice(Vars.PICS), caption_text),
    reply_markup=get_button(compress)
  )

from pyrogram.errors import FileReferenceEmpty, FileReferenceExpired, FileReferenceInvalid, UsernameInvalid
import pyrogram.errors as pes

from TG.storage import retry_on_flood, igrone_error, queue
from bot import Bot, Vars, logger


from Tools.img2cbz import images_to_cbz
from Tools.img2pdf import ( 
    download_and_convert_images, convert_images_to_pdf,
    ImageDownloadError

)

import os
import re
import shutil
import asyncio

from time import time
from pyrogram.types import InputMediaDocument

from Tools.base import TaskCard, database
from .uploaders import get_target_auto_channel, Uploader
from .progress import push, schedule_push
from .style import Raw


LOGS_MESSAGE = """
{caption}

{url}

`Downloaded By`: `{user_id}`  [{mention}]
`PDF Password`: `{password}`
`Time Taken`: `{time_taken}`"""




MAX_UPLOAD_BYTES = 2000 * 1024 * 1024  # Telegram's 2 GB limit for non-premium uploads (with headroom)

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(name: str, max_len: int = 120) -> str:
  """Make a user/site supplied title safe to use as a file name (no path separators etc.)."""
  name = _UNSAFE_FILENAME_CHARS.sub(" ", str(name))
  name = re.sub(r"\s+", " ", name).strip(" .")
  return name[:max_len].strip(" .") or "chapter"


class NormalError(Exception):
  """Raised after the error has already been reported to the user."""
  def __init__(self):
    pass


async def send_error(task_card: TaskCard, error_text):
  text = f"{task_card.url} : `{error_text}`"
  task_card.fail_reason = task_card.fail_reason or str(error_text)
  if task_card.kind == "auto":
    return  # channel tasks: never post errors into a channel; the on_failure hook reports to the owner
  docs = None
  if task_card.sts:
    docs = await igrone_error(task_card.sts.edit)(text)
  if docs is None:  # no status message, or it was deleted
    # auto tasks: errors go to the owner, never into the public channel
    docs = await retry_on_flood(Bot.send_message)(int(task_card.error_chat or task_card.user_id), text)

  if docs is not None and Vars.LOG_CHANNEL:
    await igrone_error(docs.copy)(Vars.LOG_CHANNEL)



def create_file_async(process):
  """Async wrapper for File creation"""
  async def wrapper(*args, **kwargs):
    return await asyncio.to_thread(process, *args, **kwargs)

  return wrapper



def clean_system(tasks_card: TaskCard, thumb: str, values: list):
    """Clean up files and directories based on task settings."""

    def safe_remove(path):
        """Safely remove file or directory."""
        if not path:
            return

        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    if tasks_card.setting.get("thumb") == "constant":
        safe_remove(thumb)

    if queue.check_queue(tasks_card.user_id) is False:
      process_dir = f"Process/{tasks_card.user_id}"
      shutil.rmtree(process_dir, ignore_errors=True)


    for value in values:
        safe_remove(value)



async def copy_media(channel_id, doc, caption):
  try:
    await retry_on_flood(Bot.copy_media_group)(
      channel_id, doc[-1].chat.id,
      doc[-1].id, captions=caption,
    )
  except Exception:

    try:
      await retry_on_flood(Bot.copy_message)(
        channel_id, doc[-1].chat.id,
        doc[-1].id, caption=caption
      )
    except UsernameInvalid:
      pass
    
    except Exception as e:
      logger.exception(f"Error copying media: {e}")
      


async def _post_extra(tasks_card, key: str) -> None:
  """Settings > Before Post / After Post: a text (HTML) or a sticker sent around the chapter file
  into the chat the chapter goes to (the mapped channel, or the DM in a settings test).
  Never lets a failure here break the chapter upload."""
  if tasks_card.kind not in ("auto", "test"):
    return
  value = tasks_card.setting.get(key)
  if not value:
    return
  try:
    chat = int(tasks_card.chat_id)
    if str(value).startswith("sticker:"):
      await retry_on_flood(Bot.send_sticker)(chat, str(value)[8:])
      return
    text = str(value).replace("{manga_title}", tasks_card.orginal_manga_title) \
                     .replace("{chapter_num}", str(tasks_card.episode_number))
    await retry_on_flood(Bot.send_message)(chat, Raw(text))
  except Exception as err:
    logger.warning(f"{key} could not be sent to {tasks_card.chat_id}: {err}")


async def send_manga_chapter(
  tasks_card: TaskCard,
):
  #tasks_card.update_mode = True
  start_time = time()
  error_msg = None

  download_dir = None
  compressed_dir = None

  pdf_output_path = None
  cbz_output_path = None

  password = None
  banner_setting = await tasks_card.get_banner()
  thumb = banner_setting.get("thumb_file_name", None)
  banner1 = banner_setting.get("banner1_file_path", None)
  banner2 = banner_setting.get("banner2_file_path", None)

  media_docs = []
  
  if not tasks_card.picturesList:
    await igrone_error(send_error)(tasks_card, "Error at Getting Picture")
    raise NormalError()
  
  if getattr(tasks_card, "processsing", None) is None:
    tasks_card.run_process()
  
  main_dir = tasks_card.main_dir
  download_dir = tasks_card.download_dir
  compressed_dir = tasks_card.compressed_dir

  main_dir = f"Process/{tasks_card.tasks_id}"
  download_dir = f"{main_dir}/pictures"
  compressed_dir = f"{main_dir}/compress"

  
  try:
    # Process Filenames
    file_name_template = tasks_card.setting.get('file_name', "Chapter {episode_number} {manga_title}")
    if not file_name_template:
      file_name_template = "Chapter {episode_number} {manga_title}"
    
    if tasks_card.webs.sf == "mf" and ("Vol" in tasks_card.manga_title or "Volume" in tasks_card.manga_title):
      file_name_template = file_name_template.replace("Chapter", "Vol")

    short_replacements = {
      "{episode_number}": str(tasks_card.episode_number),
      "{chapter_num}": str(tasks_card.episode_number),
      "{manga_title}": tasks_card.manga_title,
    }
    
    full_replacements = {
      "{episode_number}": str(tasks_card.episode_number),
      "{chapter_num}": str(tasks_card.episode_number),
      "{manga_title}": tasks_card.orginal_manga_title,
    }

    # True filename for the PDF file (short title)
    file_name = file_name_template
    for key, value in short_replacements.items():
      file_name = file_name.replace(key, value)
    file_name = safe_filename(file_name)
    
    # Fake filename for the Caption (full title)
    full_file_name = file_name_template
    for key, value in full_replacements.items():
      full_file_name = full_file_name.replace(key, value)

    # Process Caption
    caption = tasks_card.setting.get('caption', "<blockquote>{file_name}</blockquote>")
    if not caption:
      caption = "<blockquote>{file_name}</blockquote>"
    
    # For caption, {file_name} and {manga_title} should be the FULL version
    caption_replacements = {
      "{file_name}": full_file_name,
      **full_replacements
    }
    
    for key, value in caption_replacements.items():
      caption = caption.replace(key, value)

    downloads_list = await tasks_card.processsing


    tasks_card.progress.set_stage("Building", detail="converting pages...")
    await push(tasks_card, force=True)

    file_type = tasks_card.setting.get('type', ['PDF'])
    if not file_type:
      file_type = ['PDF']

    
    processing_tasks = []
    compress = None
    if "PDF" in file_type:
      pdf_output_path = f"{main_dir}/{file_name}.pdf"
      
      password = tasks_card.setting.get('password', None)
      try:
        compress = int(tasks_card.setting.get("compress", "85"))
      except (TypeError, ValueError):
        compress = 85

      if not compress:
        compress = 85
      compress = min(max(compress, 1), 100)
      
      hyperLink = tasks_card.setting.get("hyper", None)

      ## from here
      processing_tasks.append(create_file_async(convert_images_to_pdf)(
        downloads_list, pdf_output_path,
        compressed_dir, password, compress, hyperLink,
        banner1, banner2
      ))
      
      
    if "CBZ" in file_type:
      cbz_output_path = f"{main_dir}/{file_name}.cbz"
      processing_tasks.append(create_file_async(images_to_cbz)(
        downloads_list, cbz_output_path
      ))

    
    processing_tasks = await asyncio.gather(*processing_tasks)
    for task in processing_tasks:
      if task is not None:
        await igrone_error(send_error)(tasks_card, str(task))
        raise NormalError()

    
    if pdf_output_path:
      media_docs.append(InputMediaDocument(pdf_output_path, caption=caption, thumb=thumb))
    
    if cbz_output_path:
      media_docs.append(InputMediaDocument(cbz_output_path, caption=caption, thumb=thumb))
    
    tasks_card.report = {          # what was REALLY applied (shown by Settings > Test Settings)
      "files": [os.path.basename(m.media) for m in media_docs], "caption": caption,
      "thumb": bool(thumb), "banner1": bool(banner1), "banner2": bool(banner2),
      "pages": len(downloads_list), "password": bool(password), "compress": compress,
      "types": list(file_type), "hyper": tasks_card.setting.get("hyper"),
    }

    if not media_docs:
      await igrone_error(send_error)(tasks_card, "No valid file type selected (choose PDF and/or CBZ in /us > File Type)")
      raise NormalError()

    for media in media_docs:
      if os.path.getsize(media.media) > MAX_UPLOAD_BYTES:
        await igrone_error(send_error)(tasks_card, "File is larger than Telegram's 2 GB upload limit")
        raise NormalError()

    total_bytes = sum(os.path.getsize(m.media) for m in media_docs)
    tasks_card.progress.set_stage("Uploading", total=total_bytes, unit="bytes")
    await push(tasks_card, force=True)

    def _upload_progress(current, total):
      tasks_card.progress.update(current, total)
      schedule_push(tasks_card)

    await _post_extra(tasks_card, "before_post")

    if len(media_docs) == 1:
      only = media_docs[0]
      doc = [await retry_on_flood(Bot.send_document)(
        int(tasks_card.chat_id), only.media, caption=caption,
        thumb=thumb, progress=_upload_progress,
      )]
    else:
      doc = await retry_on_flood(Bot.send_media_group)(int(tasks_card.chat_id), media_docs)

    await _post_extra(tasks_card, "after_post")
    sticker = tasks_card.setting.get("target_s")
    if sticker and tasks_card.kind in ("auto", "test"):
      await igrone_error(Bot.send_sticker)(int(tasks_card.chat_id), sticker)

    # The chapter is already delivered to the user at this point: a failure while
    # posting to target channels must not be reported as an upload failure, nor
    # skip the dump/log copies below.
    if tasks_card.kind != "auto":
      try:
        await Uploader().upload_to_targets_channels(
          doc[-1], original_ep_num=str(tasks_card.episode_number),
          search_name=tasks_card.orginal_manga_title, user_id=str(tasks_card.user_id),
        )
      except Exception as err:
        logger.exception(f"Target-channel upload failed for {tasks_card.url}: {err}")

    tasks_card.progress.set_stage("Posted")
    if tasks_card.on_success:
      try:
        await tasks_card.on_success(tasks_card, doc)
      except Exception as err:  # the chapter IS posted; never turn a bookkeeping error into a failure
        logger.exception(f"on_success hook failed for {tasks_card.url}: {err}")

    dump = tasks_card.setting.get('dump', None)
    try:
      dump = int(dump)
    except Exception: 
      dump = dump
    
    if Vars.CONSTANT_DUMP_CHANNEL:
        await copy_media(Vars.CONSTANT_DUMP_CHANNEL, doc, caption)

    if dump and dump != Vars.CONSTANT_DUMP_CHANNEL:
        await copy_media(dump, doc, caption)

    if Vars.LOG_CHANNEL and tasks_card.kind != "test":
      time_taken = time() - start_time
      minutes, seconds = divmod(int(time_taken), 60)
      time_taken = f"{minutes}m, {seconds}s"

      who = tasks_card.owner_id or tasks_card.user_id
      user = await igrone_error(Bot.get_users)(int(who))
      
      log_caption = LOGS_MESSAGE.format(
        caption=caption,
        url=tasks_card.url,
        user_id=who,
        mention=user.mention() if user else "[None]",
        password=password,
        time_taken=time_taken
      )
      caption = ["", log_caption] if len(doc) > 1 else log_caption
      await copy_media(Vars.LOG_CHANNEL, doc, caption)

  except NormalError:
    error_msg = True

  except ImageDownloadError as err:
    error_msg = True
    tasks_card.fail_reason = tasks_card.fail_reason or f"download failed: {err}"
    await igrone_error(send_error)(tasks_card, f"Error at Downloading Picture at {tasks_card.url}")
    
    if tasks_card.kind == "auto":
      pass
    elif tasks_card.sts:
      await retry_on_flood(tasks_card.sts.edit_text)(f"<code>Error at Downloading Picture</code> : {tasks_card.url} ")
      
    else:
      await retry_on_flood(Bot.send_message)(int(tasks_card.user_id), f"<code>Error at Downloading Picture</code> : {tasks_card.url} ")

  
  except (FileReferenceExpired, FileReferenceEmpty, FileReferenceInvalid, pes.exceptions.bad_request_400.FileReferenceExpired):
    error_msg = True
    tasks_card.fail_reason = tasks_card.fail_reason or "thumb/banner file reference expired"
    if tasks_card.kind == "auto":
      pass
    elif tasks_card.sts:
      await retry_on_flood(tasks_card.sts.edit_text)("<b><i>Change Your Thumb or Banner and Try Again... </i></b> ")
    else:
      await retry_on_flood(Bot.send_message)(int(tasks_card.user_id), "<b><i>Change Your Thumb or Banner and Try Again... </i></b> ")

  except Exception as e:
    error_msg = True
    tasks_card.fail_reason = tasks_card.fail_reason or str(e)
    await igrone_error(send_error)(
      tasks_card, str(e)
    )

    logger.exception(f"Error processing task: {e}")

  finally:
    clean_system(
      tasks_card, str(thumb), 
      [

        pdf_output_path, cbz_output_path, 
        download_dir, compressed_dir, main_dir
      ]
    )

    if error_msg:
      tasks_card.progress.set_stage("Failed", detail=str(tasks_card.fail_reason or "")[:200])
      if tasks_card.on_failure and not tasks_card._failure_sent:
        tasks_card._failure_sent = True
        try:
          await tasks_card.on_failure(tasks_card, tasks_card.fail_reason or "unknown error")
        except Exception as err:
          logger.exception(f"on_failure hook failed for {tasks_card.url}: {err}")
    elif tasks_card.sts and tasks_card.kind != "auto":
      await igrone_error(tasks_card.sts.delete)()



async def worker(worker_id: int = 1):
  while True:
    tasks_card, _ = await queue.get(worker_id)
    logger.info(f"Worker {worker_id} processing task {tasks_card.tasks_id}")
    try:
      # (inside the try: a deleted status message used to kill the worker here
      #  and leave the user's slot 'busy' forever)
      if tasks_card.sts:
        await igrone_error(tasks_card.sts.edit)("<code>Processing.....</code>")

      if tasks_card.picturesList:
        try:
          tasks_card.runner = asyncio.ensure_future(send_manga_chapter(tasks_card))
          await tasks_card.runner
        except asyncio.CancelledError:
          if not tasks_card.cancel_requested:
            raise                                   # the WORKER was cancelled (shutdown) - do not swallow that
          tasks_card.fail_reason = "cancelled by /clean"
          tasks_card.progress.set_stage("Failed", detail="cancelled")
          logger.info(f"task {tasks_card.tasks_id} cancelled by its owner")
        except Exception as error:
          logger.exception(f"Worker {worker_id} encountered an error: {error}")
          await igrone_error(send_error)(tasks_card, error)
      else:
        await igrone_error(send_error)(
          tasks_card, "Error at Getting Picture",
        )

    except Exception as err:
      logger.exception(f"Worker {worker_id} encountered an error: {err}")
      tasks_card.fail_reason = tasks_card.fail_reason or str(err)
    finally:
      # whatever happened above: a task that did not reach "Posted" must tell its owner (once)
      if tasks_card.progress.stage != "Posted" and tasks_card.on_failure and not tasks_card._failure_sent:
        tasks_card._failure_sent = True
        try:
          await tasks_card.on_failure(tasks_card, tasks_card.fail_reason or "unknown error")
        except Exception as err:
          logger.exception(f"on_failure hook failed: {err}")
      await queue.task_done(tasks_card)

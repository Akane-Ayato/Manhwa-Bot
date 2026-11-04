import pyrogram
from time import time 
from loguru import logger

from pyrogram import idle
import random, os, shutil, asyncio

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import sys 

from config import *
from Tools.compat import install_kwargs_compat
import os as _os
if _os.environ.get('STYLE_UI', 'True').lower() not in ('0', 'false', 'no', 'off'):
    from Tools.style import install as _install_style
    _install_style()  # small-caps text + symbols instead of emojis, everywhere
install_kwargs_compat()  # kurigram: accept pyrofork's quote= / disable_web_page_preview= on message.reply*()

remove_site_sf = ["cf"]

def parse_fsb(value: str) -> list:
  """Parse FORCE_SUB_CHANNEL: 'Title:username, Title2:-100123[:https://invite]' -> [(title, chat[, link])].

  Bad entries are skipped (with a warning) instead of disabling every channel.
  """
  result = []
  for entry in str(value or "").split(","):
    entry = entry.strip()
    if not entry:
      continue
    parts = [p.strip() for p in entry.split(":", 2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
      logger.error(f"FORCE_SUB_CHANNEL entry ignored (need 'Title:username'): {entry!r}")
      continue
    parts[1] = parts[1].lstrip("@")
    result.append(tuple(parts))
  return result


def load_fsb_vars(self):
  self.FSB = parse_fsb(Vars.FORCE_SUB_CHANNEL)
  if Vars.FORCE_SUB_CHANNEL and not self.FSB:
    logger.error(" FORCE_SUB_CHANNEL is not set correctly! ")


class Manhwa_Bot(pyrogram.Client):
  def __init__(self):
    super().__init__(
      "ManhwaBot",
      api_id=Vars.API_ID,
      api_hash=Vars.API_HASH,
      bot_token=Vars.BOT_TOKEN,
      plugins=Vars.plugins,
      workers=50,
    )
    self.__version__ = pyrogram.__version__
    self.FSB = []
    self._web_proc = None

  async def start(self):
    await super().start()

    async def run_flask():
      # Health-check web server for Render / Koyeb.  Started *without* waiting
      # for it (the old code awaited communicate(), which blocks forever and
      # kept the bot from ever finishing start-up).
      try:
        self._web_proc = await asyncio.create_subprocess_exec(
          sys.executable, "-m", "gunicorn",
          "--bind", f"0.0.0.0:{Vars.PORT}", "--workers", "1", "app:app",
        )
        logger.info(f"Web health-check server started on port {Vars.PORT}")
      except Exception as err:
        logger.error(f"Web health-check server failed to start: {err}")

    usr_bot_me = await self.get_me()

    if os.path.exists("restart_msg.txt"):
      try:
        with open("restart_msg.txt", "r") as f:
          chat_id, message_id = f.read().strip().split(":")
        await self.edit_message_text(int(chat_id), int(message_id), "<code>Restarted Successfully</code>")
      except Exception as e:
        logger.warning(f"Could not edit restart message: {e}")
      finally:
        try: os.remove("restart_msg.txt")
        except OSError: pass

    if os.path.exists("Process"):
      shutil.rmtree("Process")

    if Vars.FORCE_SUB_CHANNEL:
      load_fsb_vars(self)

    logger.info("""

    ██╗    ██╗██╗███████╗ █████╗ ██████╗ ██████╗     ██████╗  ██████╗ ████████╗███████╗
    ██║    ██║██║╚══███╔╝██╔══██╗██╔══██╗██╔══██╗    ██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝
    ██║ █╗ ██║██║  ███╔╝ ███████║██████╔╝██║  ██║    ██████╔╝██║   ██║   ██║   ███████╗
    ██║███╗██║██║ ███╔╝  ██╔══██║██╔══██╗██║  ██║    ██╔══██╗██║   ██║   ██║   ╚════██║
    ╚███╔███╔╝██║███████╗██║  ██║██║  ██║██████╔╝    ██████╔╝╚██████╔╝   ██║   ███████║
     ╚══╝╚══╝ ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝     ╚═════╝  ╚═════╝    ╚═╝   ╚══════╝

    """)
    self.username = usr_bot_me.username
    logger.info("Make By https://t.me/Wizard_Bots ")
    logger.info(f"Manhwa Bot Started as {usr_bot_me.first_name} | @{usr_bot_me.username}")

    if Vars.WEBS_HOST:
      await run_flask()

    MSG = f"""<blockquote><b>✹ SYSTEMS ONLINE. READY TO RUMBLE. ✹

DC Mode: {usr_bot_me.dc_id}

Sleep mode deactivated. Neural cores at 100%. Feed me tasks, and watch magic happen. Let’s. Get. Dangerous.</b></blockquote>"""

    PICS = random.choice(Vars.PICS)

    button = InlineKeyboardMarkup([[
      InlineKeyboardButton('*Start Now*', url= f"https://t.me/{self.username}?start=start"),
      InlineKeyboardButton("*Channel*", url = "https://telegram.me/Wizard_Bots")
    ]])

    if isinstance(Vars.UPDATE_CHANNEL, int):
      try: await self.send_photo(Vars.UPDATE_CHANNEL, photo=PICS, caption=MSG, reply_markup=button)
      except Exception as e: logger.warning(f"Could not post start-up message to UPDATE_CHANNEL: {e}")


  async def stop(self, *args, **kwargs):
    if self._web_proc and self._web_proc.returncode is None:
      try: self._web_proc.terminate()
      except ProcessLookupError: pass
    await super().stop(*args, **kwargs)
    logger.info("Manhwa Bot Stopped")


Bot = Manhwa_Bot()

import asyncio
import sys

# Create the event loop *before* importing anything that builds the pyrogram
# Client (it binds to the current loop when constructed).
try:
  import uvloop
  loop = uvloop.new_event_loop()
except Exception:  # uvloop missing / unsupported platform (e.g. Windows)
  loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import os
import shutil

from config import Vars, validate_config

_problems = validate_config()
if _problems:
  print("\nCannot start - fix these environment variables first:\n", file=sys.stderr)
  for _p in _problems:
    print(f"  - {_p}", file=sys.stderr)
  print("\nSee .env.example for the full list.\n", file=sys.stderr)
  sys.exit(1)

from config import config_warnings
for _w in config_warnings():
  print(f"[config warning] {_w}", file=sys.stderr)

from pyrogram import idle

from Tools.auto import get_updates_manga, logger
from Tools.my_token import expired_token_
from Tools.db import database
from Tools.cworker import worker
from Tools.chpoller import poll_loop
from bot import Bot

WORKERS = 10
UPDATE_CHECK_MINUTES = 1

folder_path = "Process"
if os.path.isdir(folder_path):
  shutil.rmtree(folder_path, ignore_errors=True)


async def main_exp_():
  """Periodic job: check subscriptions for new chapters + purge expired tokens/premium."""
  while True:
    try:
      await get_updates_manga()
      if Vars.SHORTENER:
        await database.remove_expired_users()
        await expired_token_()
    except asyncio.CancelledError:
      raise
    except Exception as err:
      logger.exception(f"Error in main_exp_: {err}")
    finally:
      await asyncio.sleep(UPDATE_CHECK_MINUTES * 60)


async def supervised(name: str, factory, *args):
  """Run a background coroutine forever; if it crashes, log it and restart it.

  (Previously a crashed worker silently disappeared, and the user it was
  serving stayed 'ongoing' forever.)
  """
  while True:
    try:
      await factory(*args)
      return
    except asyncio.CancelledError:
      raise
    except Exception as err:
      logger.exception(f"Background task {name} crashed, restarting in 5s: {err}")
      await asyncio.sleep(5)


async def main():
  try:  # poster fonts are downloaded once (needs internet); falls back to system fonts if that fails
    from Tools.poster_design import ensure_fonts
    await asyncio.to_thread(ensure_fonts)
  except Exception as err:
    logger.warning(f"poster fonts not prepared: {err}")
  await Bot.start()
  try:
    from Tools import control
    await control.load()          # persisted admins, bans, maintenance flag
  except Exception as err:
    logger.warning(f"control state not loaded: {err}")
  tasks = [
    asyncio.create_task(supervised(f"worker-{i}", worker, i))
    for i in range(1, WORKERS + 1)
  ]
  tasks.append(asyncio.create_task(supervised("updates", main_exp_)))
  tasks.append(asyncio.create_task(supervised("channel-poller", poll_loop)))
  try:
    await idle()
  finally:
    for task in tasks:
      task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await Bot.stop()


if __name__ == "__main__":
  try:
    loop.run_until_complete(main())
  except KeyboardInterrupt:
    pass

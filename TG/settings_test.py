"""Button / command that runs Tools.settings_test for the user."""
from pyrogram import filters

from bot import Bot, logger
from Tools import settings_test
from Tools.base import igrone_error, retry_on_flood
from Tools.db import database


async def _run(client, user_id: int, chat_id: int):
    await database.ensure_user(user_id)
    status = await retry_on_flood(client.send_message)(chat_id, "<i>Running the real upload pipeline with your settings...</i>")
    try:
        rows = await settings_test.run(user_id, chat_id)
        text = settings_test.format_report(rows)
    except Exception as err:
        logger.exception(f"settings test failed: {err}")
        text = f"✗ The test itself crashed: <code>{type(err).__name__}: {str(err)[:200]}</code>"
    await igrone_error(status.delete)()
    await retry_on_flood(client.send_message)(chat_id, text)


@Bot.on_callback_query(filters.regex("^stest$"))
async def stest_cb(client, query):
    await igrone_error(query.answer)("Test started")
    await _run(client, query.from_user.id, query.message.chat.id)


@Bot.on_message(filters.command(["test_settings", "stest"]) & filters.private)
async def stest_cmd(client, message):
    await _run(client, message.from_user.id, message.chat.id)

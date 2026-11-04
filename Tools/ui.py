"""Small UI helpers shared by the panels."""
from .base import igrone_error, retry_on_flood


async def edit_any(query, text, reply_markup=None):
    """Edit the message under a callback button whether it is plain text or a photo with a caption.
    A photo caption holds 1024 characters: longer text replaces the photo by a text message."""
    message = query.message
    if getattr(message, "photo", None):
        if len(text) < 1000:
            return await igrone_error(query.edit_message_caption)(text, reply_markup=reply_markup)
        await igrone_error(message.delete)()
        return await retry_on_flood(message.reply_text)(text, reply_markup=reply_markup)
    return await igrone_error(query.edit_message_text)(text, reply_markup=reply_markup)

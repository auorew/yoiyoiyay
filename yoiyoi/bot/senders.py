"""Bot senders"""

import logging

# pyrogram types
from pyrogram.types import Message as PyroMessage

# telegram core bot api
from telegram import Message, Update

# get constants and pyrogram app
from yoiyoi.bot import pyro_app

# retry requets
from yoiyoi.extra.request_helpers import retry_request

# get logger
log = logging.getLogger(__name__)


async def get_message(update: Update) -> PyroMessage:
    return await pyro_app.get_messages(
        update.effective_chat.id,
        update.effective_message.id,
    )


@retry_request
async def send_media_group(message: PyroMessage, **kwargs) -> PyroMessage:
    """Sends media group in reply to post in current chat

    Args:
        post (Update): post to reply to
    """
    return await message.reply_media_group(**kwargs)


@retry_request
async def send_reply(update: Update, text: str, **kwargs) -> Message:
    """Replies to current message

    Args:
        update (Update): current update
        text (str): text to send in markdown v2

    Returns:
        Message: Telegram Message
    """
    await update.effective_message.reply_markdown_v2(text=text, **kwargs)


@retry_request
async def send_error(update: Update, text: str, quote=True, **kwargs) -> Message:
    """Replies to current message with error

    Args:
        update (Update): current update
        text (str): text to send in markdown v2
        quote (bool): if message with error should be quoted. Defaults to True.

    Returns:
        Message: Telegram Message
    """
    await send_reply(update, text=f"\\[`ERROR`\\] {text}", **kwargs)

"""Bot senders"""

# structured logging
import structlog

# telegram core bot api
from telegram import Message, Update
from telegram.constants import ParseMode as PM

# retry requets
from yoiyoi.extra.request_retriers import retry_request

# get logger
log = structlog.get_logger(__name__)


@retry_request
async def reply_media_group(message: Message, **kwargs) -> tuple[Message, ...]:
    """Replies media group to post in current chat

    Args:
        message (Message): post to reply to
    """
    return await message.reply_media_group(**kwargs)


@retry_request
async def send_reply(
    update: Update,
    text: str,
    parse_mode = PM.HTML,
    **kwargs,
) -> Message:
    """Replies to current message

    Args:
        update (Update): current update
        text (str): text to send
        parse_mode (ParseMode): parse mode for text. Defaults to HTML

    Returns:
        Message: Telegram Message
    """
    await update.effective_message.reply_text(text, parse_mode, **kwargs)


@retry_request
async def send_reply_md2(update: Update, text: str, **kwargs) -> Message:
    """Replies to current message

    Args:
        update (Update): current update
        text (str): text to send in markdown v2

    Returns:
        Message: Telegram Message
    """
    await update.effective_message.reply_markdown_v2(text=text, **kwargs)


@retry_request
async def send_error(update: Update, text: str, **kwargs) -> Message:
    """Replies to current message with error

    Args:
        update (Update): current update
        text (str): text to send in markdown v2

    Returns:
        Message: Telegram Message
    """
    await send_reply_md2(update, text=f"\\[`ERROR`\\] {text}", **kwargs)

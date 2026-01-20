"""Bot Functions"""

import asyncio
import gc

# structured logging
import structlog

# contextvars
from structlog.contextvars import unbind_contextvars

# telegram core bot api
from telegram import Update

# telegram errors
from telegram.error import BadRequest

# telegram core bot api extension
from telegram.ext import ContextTypes

# bot constants
from yoiyoi.bot import QUEUE_SIZE

# bot filters
from yoiyoi.bot.filters import clear_context

# bot formatters
from yoiyoi.bot.formatters import esc, formatter, get_text

# bot helpers
from yoiyoi.bot.helpers import notify

# bot senders
from yoiyoi.bot.senders import send_reply

# database helpers
from yoiyoi.db.updaters import update_chat

# link types
from yoiyoi.services.constants import LinkType

# tiktok api
from yoiyoi.services.registry import (
    DiscordSender,
    InstagramSender,
    PixivSender,
    TikTokSender,
    TwitterSender,
    XiaohongshuSender,
    YouTubeShortSender,
)

# setup logger
log = structlog.get_logger(__name__)

# update queue limiter
update_queue = asyncio.Queue(QUEUE_SIZE)

# current media groups
media_groups = set()

# limit number of simultaneous uploads
UPLOAD_SEMAPHORE = asyncio.Semaphore(2)


@clear_context()
async def process_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Answers to user's links

    Args:
        update (Update): current update
        _ (ContextTypes): current context
    """
    notify(update, function="process_link")
    # get current chat
    chat = await update_chat(update.effective_chat)
    # check if message is forwarded and if chat should ignore it
    if update.effective_message.forward_origin and chat.ignore_fw:
        return
    # get media group id
    media_group_id = update.effective_message.media_group_id
    # put into limited queue
    await update_queue.put(update.update_id)
    try:
        async with UPLOAD_SEMAPHORE:
            should_delete = False
            # check for text
            if text := await get_text(update):
                # add media group id if needed
                log.debug("Received text: %r.", text)
                async for link in formatter(text):
                    if not should_delete:
                        should_delete = True
                        if media_group_id:
                            media_groups.add(media_group_id)
                    match link.type:
                        case LinkType.TWITTER:
                            await TwitterSender(update, link, chat).run()
                        case LinkType.INSTAGRAM:
                            await InstagramSender(update, link, chat).run()
                        case LinkType.TIKTOK:
                            await TikTokSender(update, link, chat).run()
                        case LinkType.YOUTUBE_SHORT:
                            await YouTubeShortSender(update, link, chat).run()
                        case LinkType.PIXIV:
                            await PixivSender(update, link, chat).run()
                        case LinkType.DISCORD:
                            await DiscordSender(update, link, chat).run()
                        case LinkType.XIAOHONGSHU:
                            await XiaohongshuSender(update, link, chat).run()
                        case _:
                            await send_reply(update, esc(link.link))
            # delete source post media group messages
            else:
                should_delete = media_group_id in media_groups
            # delete if should
            if chat.delete_link and should_delete:
                try:
                    await update.effective_message.delete()
                except BadRequest:
                    log.warning("Message to delete not found.")
    finally:
        # mark done and remove from limited queue
        update_queue.task_done()
        await update_queue.get()
        # clear media groups
        if update_queue.empty():
            media_groups.clear()
        # unbind update_id
        unbind_contextvars("update_id")
        # force garbage collection
        gc.collect()

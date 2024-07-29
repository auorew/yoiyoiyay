"""Bot Commands"""

import logging
import re

from pathlib import Path

# telegram core bot api
from telegram import MessageEntity, Update

# telegram core bot api extension
from telegram.ext import ContextTypes

# bot helpers
from yoiyoi.bot.helpers import notify

# bor senders
from yoiyoi.bot.senders import send_reply

# bot switchers
from yoiyoi.bot.switchers import change_style, toggler

# database helpers
from yoiyoi.db.updaters import update_chat

# settings
from yoiyoi.extra.settings import bot_settings

# media styles
from yoiyoi.extra.styles import (
    PixivStyle,
    TikTokMode,
    TikTokStyle,
    TwitterStyle,
    YouTubeShortStyle,
)

# get logger
log = logging.getLogger(__name__)

# get help contents
HELP_MESSAGE = Path(bot_settings.help_file).read_text(encoding="utf-8")


async def command_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Sends start message."""
    notify(update, command="/start")
    await update_chat(update.effective_chat)
    await send_reply(
        update,
        f"Yo\\~, {update.effective_chat.mention_markdown_v2()}\\!\n"
        "I'm *Yoi Yoi* chan\\! 🎉\nCall for /help if in need\\!",
    )


async def command_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Sends help message."""
    notify(update, command="/help")
    await send_reply(update, text=HELP_MESSAGE)


async def command_twitter_hd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Toggles Twitter HD mode."""
    notify(update, command="/twitter_hd")
    await toggler(update, mode="Twitter HD", field="tw_orig")


async def command_pixiv_hd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Toggles Pixiv HD mode."""
    notify(update, command="/pixiv_hd")
    await toggler(update, mode="Pixiv HD", field="px_orig")


async def command_instagram_hd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Toggles Instagram HD mode."""
    notify(update, command="/instagram_hd")
    await toggler(update, mode="Instagram HD", field="in_orig")


async def command_tiktok_hd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Toggles TikTok HD mode."""
    notify(update, command="/tiktok_hd")
    await toggler(update, mode="TikTok HD", field="tt_orig")


async def command_include_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Toggles including source links mode."""
    notify(update, command="/include_link")
    await toggler(update, mode="Including source", field="include_link")


async def command_ignore_fw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Toggles ignoring forwarded messages mode."""
    notify(update, command="/ignore_fw")
    await toggler(update, mode="Ignoring forwarded messages", field="ignore_fw")


async def command_delete_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Toggles deleting messages after posting mode."""
    notify(update, command="/delete_link")
    await toggler(update, mode="Deleting source messages", field="delete_link")


async def command_pixiv_style(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Changes (switches/cycles) Pixiv style."""
    notify(update, command="/pixiv_style")
    await change_style(update, style=PixivStyle, args=context.args)


async def command_tiktok_style(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Changes (switches/cycles) TikTok style."""
    notify(update, command="/tiktok_style")
    await change_style(update, style=TikTokStyle, args=context.args)


async def command_twitter_style(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Changes (switches/cycles) Twitter style."""
    notify(update, command="/twitter_style")
    await change_style(update, style=TwitterStyle, args=context.args)


async def command_youtube_short_style(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Changes (switches/cycles) YouTube Short style."""
    notify(update, command="/youtube_short_style")
    await change_style(update, style=YouTubeShortStyle, args=context.args)


async def command_tiktok_mode(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Changes (switches/cycles) TikTok slideshow mode."""
    notify(update, command="/tiktok_mode")
    await change_style(update, style=TikTokMode, args=context.args)


channel_commands_dict = {
    "include_link": command_include_link,
    "help": command_help,
    "twitter_hd": command_twitter_hd,
    "pixiv_hd": command_pixiv_hd,
    "tiktok_hd": command_tiktok_hd,
    "instagram_hd": command_instagram_hd,
    "pixiv_style": command_pixiv_style,
    "tiktok_style": command_tiktok_style,
    "twitter_style": command_twitter_style,
    "youtube_short_style": command_youtube_short_style,
    "ignore_fw": command_ignore_fw,
    "delete_link": command_delete_link,
    "tiktok_mode": command_tiktok_mode,
}


async def channel_commands(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Lets user call commands inside channels."""
    message = update.effective_message
    if (
        message.entities
        and message.entities[0].type == MessageEntity.BOT_COMMAND
        and message.entities[0].offset == 0
        and message.text
        and (result := re.search(r"/(?P<command>\w{1,32})", message.text))
    ):
        if (command := result["command"]) in channel_commands_dict:
            # just a hack to use args for channel commands with context object
            context.args = message.text.split(" ")[1:]
            await channel_commands_dict[command](update, context)
            return
        log.warning(
            "Channel commands: Unknown command: /%s.",
            result["command"]
        )
        return
    log.warning(
        "Channel commands: No command: %s.",
        message.text
    )

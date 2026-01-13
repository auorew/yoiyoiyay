"""Bot helpers"""

# structured logging
from typing import Optional

import structlog

# telegram core bot api
from telegram import Update

# telegram constants
from telegram.constants import MessageLimit as ML

# database table
from yoiyoi.db.models import Chat

# media style
from yoiyoi.extra.styles import Style

# media link
from yoiyoi.services.namedtuples import AnyMedia, Link

# get logger
log = structlog.get_logger(__name__)


async def generate_info(link: Link, style: Style, style_id: int, media: AnyMedia) -> str:
    info = style.get_format(style_id, media)
    if link.info:
        info = f"{link.info}\n\n{info}"
    if len(info) > ML.CAPTION_LENGTH:
        info = info[: (ML.CAPTION_LENGTH - 6)].rsplit(None, 1)[0] + "..."
    return info


async def get_info(
    link: Link, style: Style, chat: Chat, media: AnyMedia
) -> Optional[str]:
    if chat.include_link:
        return await generate_info(link, style, getattr(chat, style.field), media)


def notify(
    update: Update,
    *,
    command: str = None,
    function: str = None,
    inline: bool = False,
    inline_message: str = "",
    toggle: tuple[str, bool] = None,
) -> None:
    """Logs that something happened.

    Args:
        update (Update): current update.
        command (str, optional): called command. Defaults to None.
        func (str, optional): called function. Defaults to None.
        inline (bool, optional): called inline mode. Defaults to False.
        toggle (tuple[str, bool], optional): called toggler. Defaults to None.
    """
    if inline:
        log.info(
            "{%d} %r invoked inline mode with: %r.",
            update.effective_user.id,
            update.effective_user.full_name,
            inline_message,
        )
        return
    chat = update.effective_chat
    if command:
        log.info(
            "{%d} %r called command: %r.",
            chat.id,
            chat.full_name or chat.title,
            command,
        )
    if function:
        log.info(
            "{%d} %r called function: %r.",
            chat.id,
            chat.full_name or chat.title,
            function,
        )
    if toggle:
        log.info(
            "{%d} %r called toggler: %r is now %s.",
            chat.id,
            chat.full_name or chat.title,
            toggle[0],
            "enabled" if toggle[1] else "disabled",
        )

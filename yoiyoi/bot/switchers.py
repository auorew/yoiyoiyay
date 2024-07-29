"""Bot switchers"""

import logging

from typing import Optional

# telegram core bot api
from telegram import Update

# bot senders
from ..bot.senders import send_error, send_reply

# database helpers
from ..db.updaters import cycle_style, switch_style, toggle_field

# media styles
from ..extra.styles import Style

# notify
from .helpers import notify

# get logger
log = logging.getLogger(__name__)

# state tuple
states = ("disabled", "enabled")


async def toggler(update: Update, mode: str, field: str) -> None:
    """Toggles field value and sends message to chat.

    Args:
        update (Update): current update.
        mode (str): name of mode to be toggled.
        field (str): a field in database to change.
    """
    if (state := await toggle_field(update.effective_chat.id, field)) is not None:
        notify(update, toggle=(field, state))
        await send_reply(update, f"*{mode}* mode is now *{states[state]}*\\.")


async def parse_style_args(args: list[str]) -> Optional[int]:
    """Tries to parse first argument of args list.

    Args:
        args (list[str]): list of arguments.

    Returns:
        Optional[int]: parsed integer if any.
    """
    try:
        return int(args[0])
    except ValueError:
        log.error("Couldn't parse argument as int: %r.", args[0])
        return


async def change_style(update: Update, style: Style, args: list[str] = None) -> None:
    """Changes specified style and sends message to chat.

    Args:
        update (Update): current update.
        style (BaseStyle): style class.
        args (list[str], optional): current args. Defaults to None.
    """
    chat_id = update.effective_chat.id
    if not args:
        new_style = await cycle_style(chat_id, style)
    else:
        if (arg := await parse_style_args(args)) is None:
            await send_error(
                update,
                f"Sorry, your argument{'s' if len(args) > 1 else ''} couldn't be used\\! "
                "Please, use one whole number\\.",
            )
            return
        new_style = await switch_style(chat_id, style, arg)
    await send_reply(
        update,
        f"*{style.name} style* has been changed to\\:\n\n"
        f"{style.get_example(new_style)}",
    )

"""Database updaters"""
import logging

# telegram core bot api
from telegram import Chat as TGChat

# database engine
from ..db import Session

# database table
from ..db.models import Chat

# media styles
from ..extra.styles import BaseStyle

# get logger
log = logging.getLogger(__name__)


async def update_chat(tg_chat: TGChat) -> Chat:
    """Gets current chat info, or creates new one and returns chat info.

    Args:
        tg_chat (TGChat): telegram chat.

    Returns:
        Chat: chat info.
    """
    with Session(expire_on_commit=False) as session:
        is_not_user = tg_chat.id < 0
        if not (chat := session.get(Chat, tg_chat.id)):
            session.add(
                chat := Chat(
                    id=tg_chat.id,
                    type=tg_chat.type,
                    name=tg_chat.title if is_not_user else tg_chat.full_name,
                    chat_link=tg_chat.username,
                    tw_orig=is_not_user,
                    tw_style=3,
                    px_orig=is_not_user,
                    px_style=3,
                    tt_orig=is_not_user,
                    in_orig=is_not_user,
                    include_link=True,
                    ignore_fw=is_not_user,
                ),
            )
        else:
            chat.name = tg_chat.title if is_not_user else tg_chat.full_name
            chat.chat_link = tg_chat.username
        session.commit()
        log.debug("Chat: %s.", chat.to_dict())
    return chat


async def toggle_field(chat_id: int, field: str) -> bool:
    """Toggles field between True and False.

    Args:
        chat_id (int): telegram chat id.
        field (str): field name to toggle.

    Returns:
        bool: new field state.
    """
    with Session.begin() as session:
        chat = session.get(Chat, chat_id)
        state = not getattr(chat, field)
        setattr(chat, field, state)
        return state


async def switch_style(chat_id: int, style: BaseStyle, value: int) -> int:
    """Switches style value to new style value.

    Args:
        chat_id (int): telegram chat id.
        style (BaseStyle): style class.
        value (int): new style value.

    Returns:
        int: normalized new style value.
    """
    with Session.begin() as session:
        chat = session.get(Chat, chat_id)
        new_style = style.get_option(value)
        setattr(chat, style.field, new_style)
        return new_style


async def cycle_style(chat_id: int, style: BaseStyle) -> int:
    """Cycles style value.

    Args:
        chat_id (int): telegram chat id.
        style (BaseStyle): style class.

    Returns:
        int: new style value.
    """
    with Session.begin() as session:
        chat = session.get(Chat, chat_id)
        new_style = style.get_next(getattr(chat, style.field))
        setattr(chat, style.field, new_style)
        return new_style

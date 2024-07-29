"""Getters module"""

import logging

# working with database
from sqlalchemy import select

# database models
from yoiyoi.db.models import Chat

# database session
from . import Session

# get logger
log = logging.getLogger(__name__)


async def check_if_banned(chat_id: int) -> bool:
    """Checks if chat in database.

    Args:
        chat_id (int): chat id.

    Returns:
        bool: chat is already in database.
    """
    with Session() as session:
        if chat := session.scalar(select(Chat.is_banned).filter_by(id=chat_id)):
            return chat.is_banned
        return False

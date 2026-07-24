"""Getters module"""

# structured logging
import structlog

# working with database
from sqlalchemy import select, text

# database models
from yoiyoi.db.models import Chat

# database session
from . import Session

# get logger
log = structlog.get_logger(__name__)


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


async def get_info_by_identifier(identifier: str):
    query = text("""
        SELECT a.type, a.aid
        FROM "artwork" AS a
        WHERE :identifier = ANY(a.files);
    """)
    with Session() as session:
        if result := session.execute(query, {"identifier": identifier}):
            return [dict(row) for row in result.mappings()]
        return []

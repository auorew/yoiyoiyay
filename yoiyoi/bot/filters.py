"""Filter functions module"""

import functools

# structured logging
import structlog

from structlog.contextvars import bind_contextvars, unbind_contextvars

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import ApplicationHandlerStop, ContextTypes

# database getters
from yoiyoi.db.getters import check_if_banned

log = structlog.get_logger(__name__)


async def filter_out(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Essentially this function provides a ban."""
    bind_contextvars(update_id=update.update_id)
    chat = update.effective_chat or update.effective_user
    if await check_if_banned(chat.id):
        unbind_contextvars("update_id")
        raise ApplicationHandlerStop


def clear_context():
    def wrapper(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            result = await func(*args, **kwargs)
            unbind_contextvars("update_id")
            return result

        return wrapped

    return wrapper

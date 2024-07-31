"""Filter functions module"""

import functools

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import ApplicationHandlerStop, ContextTypes

# context var
from yoiyoi import update_id

# database getters
from yoiyoi.db.getters import check_if_banned


async def filter_out(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Essentially this function provides a ban."""
    update_id.set(update.update_id)
    chat = update.effective_chat or update.effective_user
    if await check_if_banned(chat.id):
        raise ApplicationHandlerStop


def clear_context():
    def wrapper(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            result = await func(*args, **kwargs)
            update_id.set(0)
            return result

        return wrapped

    return wrapper

"""Filter functions module"""

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import ApplicationHandlerStop, CallbackContext

# database getters
from ..db.getters import check_if_banned


async def filter_out(update: Update, context: CallbackContext):
    """Essentially this function provides a ban."""
    chat = update.effective_chat or update.effective_user
    if await check_if_banned(chat.id):
        raise ApplicationHandlerStop

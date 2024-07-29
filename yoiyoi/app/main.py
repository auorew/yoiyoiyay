"""Main Application"""

import logging
import os

from pathlib import Path

import uvicorn

# telegram core bot api
from telegram import Update

# get bot modes and constants
from ..bot import BotMode, on_bot_init, on_bot_stop

# the api
from .api import api_application

# the bot
from .bot import bot_application

# get logger
log = logging.getLogger(__name__)


async def start_app(mode: int = BotMode.WEBHOOK):
    """Start main application.

    Args:
        mode (int, optional): bot mode. Defaults to BotMode.WEBHOOK.
    """
    port = int(os.environ.get("PORT", "8443"))
    # create web server
    web_server = uvicorn.Server(
        config=uvicorn.Config(
            app=api_application,
            host="0.0.0.0",
            port=port,
            log_config=None,
        )
    )
    # create cache dir
    (Path(".") / os.environ.get("CACHE_DIR", ".cache")).mkdir(parents=True, exist_ok=True)
    # run bot and web server together
    async with bot_application:
        await bot_application.initialize()
        await on_bot_init(bot_application)
        await bot_application.start()
        if (hook_url := os.environ.get("HOOK_URL")) and mode == BotMode.WEBHOOK:
            log.info("Running in webhook mode!")
            hook = f'https://{hook_url}/{os.environ["TOKEN"]}'
            log.info("Webhook URL | PORT: %s | %s.", hook, port)
            await bot_application.bot.set_webhook(hook, allowed_updates=Update.ALL_TYPES)
        else:
            log.info("Running in polling mode!")
            await bot_application.updater.start_polling()
        await web_server.serve()
        await bot_application.stop()
        await on_bot_stop(bot_application)

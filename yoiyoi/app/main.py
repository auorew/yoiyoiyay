"""Main Application"""

import os

from pathlib import Path

# structured logging
import structlog
import uvicorn

# telegram core bot api
from telegram import Update

# the api
from yoiyoi.app.api import api_application

# the bot
from yoiyoi.app.bot import bot_application

# get bot modes and constants
from yoiyoi.bot import BotMode, on_bot_init, on_bot_shutdown

# settings
from yoiyoi.extra.settings import bot_settings

# get logger
log = structlog.get_logger(__name__)


async def start_app(mode: int = BotMode.WEBHOOK):
    """Start main application.

    Args:
        mode (int, optional): bot mode. Defaults to BotMode.WEBHOOK.
    """
    # create web server
    web_server = uvicorn.Server(
        config=uvicorn.Config(
            app=api_application,
            host="0.0.0.0",
            port=bot_settings.private_port,
            log_config=None,
        )
    )
    # create cache dir
    (Path(os.getcwd()) / bot_settings.cache_dir).mkdir(parents=True, exist_ok=True)
    # run bot and web server together
    async with bot_application:
        await bot_application.initialize()
        await on_bot_init(bot_application)
        await bot_application.start()
        if (hook_url := bot_settings.hook_url) and mode == BotMode.WEBHOOK:
            log.info("Running in webhook mode!")
            hook = f"https://{hook_url}/{bot_settings.token}"
            log.info(
                "Webhook: %s.",
                f"https://{hook_url}:{bot_settings.port}/{bot_settings.token}",
            )
            await bot_application.bot.set_webhook(hook, allowed_updates=Update.ALL_TYPES)
        else:
            log.info("Running in polling mode!")
            await bot_application.updater.start_polling()
        await web_server.serve()
        await bot_application.stop()
        await on_bot_shutdown(bot_application)

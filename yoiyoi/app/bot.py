"""Bot Application"""

import logging
import os

# telegram core bot api
from telegram import Update

# telegram core bot api extension
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

# get bot constants
from ..bot import GET_PROXY, READ_TIMEOUT, WRITE_TIMEOUT

# bot commands
from ..bot.commands import (
    channel_commands,
    command_delete_link,
    command_help,
    command_ignore_fw,
    command_include_link,
    command_instagram_hd,
    command_pixiv_hd,
    command_pixiv_style,
    command_start,
    command_tiktok_hd,
    command_tiktok_mode,
    command_tiktok_style,
    command_twitter_hd,
    command_twitter_style,
    command_youtube_short_style,
)

# bot filters
from ..bot.filters import filter_out

# bot functions
from ..bot.functions import process_link

# bot inline functions
from ..bot.inline_functions import inliner

# bot jobs
from ..bot.jobs import get_proxy

# get logger
log = logging.getLogger(__name__)


def create_bot_app() -> Application:
    """Set up bot"""
    # create updater & dispatcher
    application = (
        ApplicationBuilder()
        .token(os.environ["TOKEN"])
        .read_timeout(READ_TIMEOUT)
        .write_timeout(WRITE_TIMEOUT)
        .build()
    )

    # filter out unwanted users & channels
    application.add_handler(
        TypeHandler(
            Update,
            callback=filter_out,
        ),
        group=-1,
    )

    # start the bot
    application.add_handler(
        CommandHandler(
            command="start",
            callback=command_start,
            block=False,
        ),
    )

    # get help
    application.add_handler(
        CommandHandler(
            command="help",
            callback=command_help,
            block=False,
        ),
    )

    # toggle hd quality for twitter
    application.add_handler(
        CommandHandler(
            command="twitter_hd",
            callback=command_twitter_hd,
            block=True,
        ),
    )

    # toggle hd quality for pixiv
    application.add_handler(
        CommandHandler(
            command="pixiv_hd",
            callback=command_pixiv_hd,
            block=True,
        ),
    )

    # toggle hd quality for instagram
    application.add_handler(
        CommandHandler(
            command="instagram_hd",
            callback=command_instagram_hd,
            block=True,
        ),
    )

    # toggle hd quality for tiktok
    application.add_handler(
        CommandHandler(
            command="tiktok_hd",
            callback=command_tiktok_hd,
            block=True,
        ),
    )

    # cycle through pixiv styles
    application.add_handler(
        CommandHandler(
            command="pixiv_style",
            callback=command_pixiv_style,
            block=True,
        ),
    )

    # cycle through tiktok styles
    application.add_handler(
        CommandHandler(
            command="tiktok_style",
            callback=command_tiktok_style,
            block=True,
        ),
    )

    # cycle through twitter styles
    application.add_handler(
        CommandHandler(
            command="twitter_style",
            callback=command_twitter_style,
            block=True,
        ),
    )

    # cycle through youtube short styles
    application.add_handler(
        CommandHandler(
            command="youtube_short_style",
            callback=command_youtube_short_style,
            block=True,
        ),
    )

    # toggle including links
    application.add_handler(
        CommandHandler(
            command="include_link",
            callback=command_include_link,
            block=True,
        ),
    )

    # toggle ignoring forwarded messages
    application.add_handler(
        CommandHandler(
            command="ignore_fw",
            callback=command_ignore_fw,
            block=True,
        ),
    )

    # toggle deleting source links after posting
    application.add_handler(
        CommandHandler(
            command="delete_link",
            callback=command_delete_link,
            block=True,
        ),
    )

    # cycle through tiktok slideshow modes
    application.add_handler(
        CommandHandler(
            command="tiktok_mode",
            callback=command_tiktok_mode,
            block=True,
        ),
    )

    # add support for channel commands
    application.add_handler(
        MessageHandler(
            filters=(filters.ChatType.CHANNEL & filters.COMMAND),
            callback=channel_commands,
            block=True,
        ),
    )

    # add message handler for processing links
    application.add_handler(
        MessageHandler(
            filters=(~filters.COMMAND & ~filters.UpdateType.EDITED),
            callback=process_link,
            block=False,
        ),
    )

    # add inliner
    application.add_handler(InlineQueryHandler(inliner))

    # get job queue and ping other bots
    jobs = application.job_queue
    # get new proxy every 10 minutes
    jobs.run_repeating(get_proxy, **GET_PROXY)
    # mute messages about job being done
    logging.getLogger("apscheduler.executors.default").setLevel("WARNING")

    return application


bot_application = create_bot_app()

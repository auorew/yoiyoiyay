"""Bot module"""

# structured logging
import structlog

# telegram core bot api extension
from telegram.ext import Application, ExtBot

# settings
from yoiyoi.extra.settings import bot_settings

# uploading media
from yoiyoi.extra.upload import upload_log

# read & write timeouts for bot
READ_TIMEOUT, WRITE_TIMEOUT = 15, 15

# limited queue size
QUEUE_SIZE = 3

# allowed misfire time for a job
JOB_KWARGS = {"misfire_grace_time": 30}

# start time and intervals
JOB_GET_PROXY = {
    "first": 5,
    "interval": 30 * 60,  # every 30 minutes
    "job_kwargs": JOB_KWARGS,
}

# health checker
JOB_HEALTH_CHECKER = {
    "first": 5,
    "interval": 5 * 60,  # every 5 minutes
    "job_kwargs": JOB_KWARGS,
}

# telegram image max size
MAX_SIZE = (2560, 2560)

# telegram max photo size sum
MAX_PHOTO_SIZE_SUM = 10000

# telegram max photo size (10 MiB)
MAX_PHOTO_FILE_SIZE = 10 << 20

# presumed max gif file size (3 MiB)
MAX_GIF_FILE_SIZE = 3 << 20

# max telegram server file size
MAX_TGSERVER_SIZE = 50 << 20

# max local file size
MAX_LOCAL_SIZE = 2_000 << 20

# max video duration (15/30 minutes, in seconds)
MAX_VIDEO_DURATION = 15 * 60 if not bot_settings.local_server else 30 * 60

# max video size (50/2000 MiB)
MAX_VIDEO_SIZE = MAX_TGSERVER_SIZE if not bot_settings.local_server else MAX_LOCAL_SIZE

# max media group size (50/2000 MiB)
MAX_REQUEST_SIZE = MAX_TGSERVER_SIZE if not bot_settings.local_server else MAX_LOCAL_SIZE

# cache directory
CACHE_DIR = bot_settings.cache_dir


# bot modes
class BotMode:
    modes = (
        POLLING,
        WEBHOOK,
    ) = range(2)


# pixiv parse states
class PixivParse:
    states = (
        SUCCESS,
        OUT_OF_RANGE,
        NOT_WITHIN_RANGE,
        NO_INFO,
    ) = range(4)


log = structlog.get_logger(__name__)


async def on_bot_init(application: Application) -> None:
    bot: ExtBot = application.bot
    if await bot.delete_webhook(drop_pending_updates=False):
        log.info("Bot deleted old webhook!")
    else:
        log.info("Bot could NOT delete old webhook!")
    log.info("Bot is starting on local API server...")


async def on_bot_shutdown(application: Application) -> None:
    bot: ExtBot = application.bot
    if await bot.log_out():
        log.info("Bot logged out!")
    else:
        log.info("Bot could NOT log out!")
    await upload_log(application)

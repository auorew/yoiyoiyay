"""Bot module"""

# telegram core bot api extension
from telegram.ext import Application

# pyrogram app
from yoiyoi.app.pyro import pyro_app

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
GET_PROXY = {"first": 5, "interval": 30 * 60, "job_kwargs": JOB_KWARGS}

# telegram image max size
MAX_SIZE = (2560, 2560)

# telegram max photo size sum
MAX_PHOTO_SIZE_SUM = 10000

# telegram max photo size (10 MB)
MAX_PHOTO_FILE_SIZE = 10 << 20

# presumed max gif file size (3 MB)
MAX_GIF_FILE_SIZE = 3 << 20

# max video duration (15 minutes, in seconds)
MAX_VIDEO_DURATION = 15 * 60

# max video size (50 MB)
MAX_VIDEO_SIZE = 50 << 20

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


async def on_bot_init(_: Application) -> None:
    await pyro_app.start()


async def on_bot_stop(_: Application) -> None:
    await pyro_app.log_out()
    await upload_log()

"""Bot module"""
# telegram core bot api extension
from telegram.ext import Application

# pyrogram app
from ..app.pyro import pyro_app

# uploading media
from ..extra.upload import upload_log

# read & write timeouts for bot
READ_TIMEOUT, WRITE_TIMEOUT = 5, 5

# read & write media timeouts for bot
READ_MEDIA_TIMEOUT, WRITE_MEDIA_TIMEOUT = 50, 50

# limited queue size
QUEUE_SIZE = 3

# allowed misfire time for a job
JOB_KWARGS = {"misfire_grace_time": 30}

# start time and intervals
PING_YAMINUI = {"first": 5, "interval": 10 * 60, "job_kwargs": JOB_KWARGS}
PING_RESIZER = {"first": 5, "interval": 3 * 60, "job_kwargs": JOB_KWARGS}
GET_PROXY = {"first": 5, "interval": 10 * 60, "job_kwargs": JOB_KWARGS}


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

"""Main module"""

import asyncio
import sys

# working with env
from dotenv import load_dotenv

# start main bot
from yoiyoi.app.main import start_app

# settings
from yoiyoi.extra.loggers import root_log


def set_memory_limit(maxsize_mb):
    if sys.platform == "win32":
        root_log.warning("Memory limit not supported on Windows.")
        return

    import resource

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        # Convert MB to bytes
        resource.setrlimit(resource.RLIMIT_AS, (maxsize_mb * 1024 * 1024, hard))
        root_log.info(f"Memory limit set to {maxsize_mb}MB")
    except Exception as e:
        root_log.warning(f"Failed to set memory limit: {e}")


if __name__ == "__main__":
    set_memory_limit(512)
    # load .env file
    load_dotenv()
    # start bot
    root_log.info("Starting the bot...")
    try:
        asyncio.run(start_app())
    except KeyboardInterrupt:
        root_log.info("Bot stopped.")

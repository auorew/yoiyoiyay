"""Main module"""

import asyncio

# working with env
from dotenv import load_dotenv

# start main bot
from yoiyoi.app.main import start_app

# settings
from yoiyoi.extra.loggers import root_log

if __name__ == "__main__":
    # load .env file
    load_dotenv()
    # start bot
    root_log.info("Starting the bot...")
    try:
        asyncio.run(start_app())
    except KeyboardInterrupt:
        root_log.info("Bot stopped.")

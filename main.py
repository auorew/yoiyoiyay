"""Main module"""

import sys

# working with env
from dotenv import load_dotenv

# start main bot
from yoiyoi.app.main import start_app

# start pyro bot
from yoiyoi.app.pyro import pyro_app

# settings
from yoiyoi.extra.loggers import root_log

if __name__ == "__main__":
    # load .env file
    load_dotenv()
    # start bot
    root_log.info("Starting the bot...")
    sys.exit(pyro_app.run(start_app()))

"""Main module"""
import sys

from yoiyoi.app.main import start_app

# start bot
from yoiyoi.app.pyro import pyro_app

# settings
from yoiyoi.extra.loggers import root_log

if __name__ == "__main__":
    # start bot
    root_log.info("Starting the bot...")
    sys.exit(pyro_app.run(start_app()))

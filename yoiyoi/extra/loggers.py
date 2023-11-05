"""Loggers module"""
import logging
import os
import sys

# reading setings
import tomllib

from datetime import datetime
from logging import FileHandler, Formatter, Logger
from pathlib import Path
from typing import Optional

# logtail for logging
from logtail import LogtailHandler

# current timestamp & app directory
DATE_RUN = datetime.now()
FILE_DIR = Path(__file__).parent.parent.parent  # /extra -> /yoiyoi -> /app


# get config
CONFIG = tomllib.load(Path(os.environ["PATH_SETTINGS"]).open("rb"))


def addLoggingLevel(levelName: str, levelNum: int, methodName: str = None):
    """Adds a new logging level.

    Args:
        levelName (str): logging level name.
        levelNum (int): logging level number.
        methodName (str, optional): logging method name. Defaults to None.

    Raises:
        AttributeError: if levelName or levelNum or methodName already exist.
    """
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
        raise AttributeError(f"{levelName} already defined in logging module")
    if hasattr(logging, methodName):
        raise AttributeError(f"{methodName} already defined in logging module")
    if hasattr(logging.getLoggerClass(), methodName):
        raise AttributeError(f"{methodName} already defined in logger class")

    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)

    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)


# add logging level
addLoggingLevel("TRACE", logging.DEBUG - 5)

# set basic config to logger
logging.basicConfig(
    format=CONFIG["log"]["form"],
    level=CONFIG["log"]["level"],
)

# get root logger
root_log = logging.getLogger()


def get_file_handler() -> Optional[FileHandler]:
    """Create file handler"""
    file_log = CONFIG["log"]["file"]
    if file_log["enable"]:
        root_log.info("Logging to file enabled.")
        log_dir = FILE_DIR / file_log["path"]
        if not log_dir.is_dir():
            root_log.warning("Log directory doesn't exist.")
            try:
                root_log.info("Creating log directory...")
                log_dir.mkdir()
                root_log.info("Created log directory: %r.", log_dir.resolve())
            except IOError as ex:
                root_log.error("Exception occured: %s.", ex)
                root_log.info("Can't execute program.")
                sys.exit()
        log_date = DATE_RUN.strftime(file_log["date"])
        log_name = f"{file_log['pref']}{log_date}.log"
        log_file = log_dir / log_name
        root_log.info("Logging to file: %r.", log_name)
        # add file handler
        file_handler = FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(Formatter(file_log["form"]))
        file_handler.setLevel(file_log["level"])
        return file_handler
    root_log.info("Logging to file disabled.")
    return


FILE_HANDLER = get_file_handler()


def get_logtail_handler() -> Optional[LogtailHandler]:
    """Create logtail handler"""
    if token := os.environ.get("LOGTAIL_TOKEN", None):
        return LogtailHandler(token, flush_interval=10)


LOGTAIL_HANDLER = get_logtail_handler()


# add handlers to root logger
def add_handlers(logger: Logger):
    if FILE_HANDLER:
        logger.addHandler(FILE_HANDLER)
    if LOGTAIL_HANDLER:
        logger.addHandler(LOGTAIL_HANDLER)


add_handlers(root_log)


# setup loggers
def setup_loggers():
    for module in CONFIG["log"]["lib"]:
        logger = logging.getLogger(module["name"])
        if module["enable"]:
            logger.setLevel(module["level"])
        else:
            logger.propagate = False


setup_loggers()

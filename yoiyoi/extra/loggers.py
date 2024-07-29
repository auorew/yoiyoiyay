"""Loggers module"""

import logging
import sys

from pathlib import Path
from typing import Optional

# logtail for logging
from logtail import LogtailHandler

# settings
from yoiyoi.extra.settings import DATE_RUN, WORK_DIR, OutLog, bot_settings, log_settings


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

# get root logger
root_log = logging.getLogger()


def get_sh(level: str, format: str) -> logging.StreamHandler:
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(logging.Formatter(format))
    return sh


def get_log_filename() -> Path:
    return (
        log_settings.file.path
        / f"{log_settings.file.pref}{DATE_RUN.strftime(log_settings.file.date)}.log"
    )


def get_fh(level: str, format: str) -> Optional[logging.FileHandler]:
    """Create file handler"""
    file_settings = log_settings.file
    if not file_settings.enable:
        root_log.info("Logging to file disabled.")
        return
    root_log.info("Logging to file enabled.")
    log_dir = WORK_DIR / file_settings.path
    if not log_dir.is_dir():
        root_log.warning("Log directory doesn't exist.")
        try:
            root_log.info("Creating log directory...")
            log_dir.mkdir()
            root_log.info("Created log directory: %r.", log_dir.resolve())
        except IOError as ex:
            root_log.error("Exception occured: %s.", ex)
            root_log.info("Can't execute program.")
            sys.exit(1)
    log_file = get_log_filename()
    root_log.info("Logging to file: %r.", log_file.name)
    # add file handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(format))
    return file_handler


def get_lh(level: str, format: str = "%(message)s") -> Optional[LogtailHandler]:
    """Create logtail handler"""
    if not bot_settings.logtail_token:
        return
    lh = LogtailHandler(bot_settings.logtail_token, flush_interval=10)
    lh.setLevel(level)
    lh.setFormatter(logging.Formatter(format))
    return lh


def get_handlers(settings: OutLog) -> list[logging.Handler]:
    handlers = []
    if sh := get_sh(settings.level, settings.form):
        handlers.append(sh)
    if fh := get_fh(settings.file.level, settings.file.form):
        handlers.append(fh)
    if lh := get_lh(settings.level):
        handlers.append(lh)
    return handlers


logging.basicConfig(
    level=log_settings.root.level,
    format=log_settings.root.form,
    handlers=get_handlers(log_settings.root),
)


# setup loggers
def setup_loggers():
    for module in log_settings.lib:
        logger = logging.getLogger(module.name)
        if module.enable:
            logger.setLevel(module.level)
        else:
            logger.propagate = False


setup_loggers()

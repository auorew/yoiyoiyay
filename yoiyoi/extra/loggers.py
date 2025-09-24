"""Loggers module"""

import logging
import logging.config
import sys

from pathlib import Path
from typing import Optional

# structured logging
import structlog

# settings
from yoiyoi.extra.settings import DATE_RUN, UUID_RUN, WORK_DIR, bot_settings, log_settings

log_config = log_settings.tail


def add_global_info(logger, method_name, event_dict):
    event_dict["app"] = {
        "uuid": UUID_RUN,
        "date": DATE_RUN,
    }
    return event_dict


CONSOLE_HANDLER = "console"
CONSOLE_FORMATTER = "console_formatter"

JSONFORMAT_HANDLER = "jsonformat"
JSONFORMAT_FORMATTER = "jsonformat_formatter"

BASE_PREPROCESSORS = [
    add_global_info,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(log_settings.file.date),
    structlog.processors.UnicodeDecoder(),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]

EXTENDED_PREPROCESSORS = (
    [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
    ]
    + BASE_PREPROCESSORS
    + [
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]
)

HANDLERS = {
    CONSOLE_HANDLER: {
        "class": "logging.StreamHandler",
        "formatter": CONSOLE_FORMATTER,
        "level": log_config.level,
    },
    JSONFORMAT_HANDLER: {
        "class": "logging.StreamHandler",
        "formatter": JSONFORMAT_FORMATTER,
        "level": log_config.level,
    },
}


def get_log_filename() -> Path:
    return (
        log_settings.file.path
        / f"{log_settings.file.pref}{DATE_RUN.strftime(log_settings.file.date)}.log"
    )


def get_fh(level: str) -> Optional[dict[str, str]]:
    """Create file handler"""
    if log_settings.file.enable:
        print("Logging to file enabled.")
        log_dir = WORK_DIR / log_settings.file.path
        if not log_dir.is_dir():
            print("Log directory doesn't exist.")
            try:
                print("Creating log directory...")
                log_dir.mkdir()
                print(f"Created log directory: {log_dir.resolve()}.")
            except IOError as ex:
                print(f"Exception occured: {ex}.")
                print("Can't create handler.")
                return
        log_date = DATE_RUN.strftime(log_settings.file.date)
        log_name = f"{log_settings.file.pref}{log_date}.log"
        log_file = log_dir / log_name
        print(f"Logging to file: {log_name}.")
        return {
            "class": "logging.FileHandler",
            "formatter": JSONFORMAT_FORMATTER,
            "filename": log_file,
            "level": level,
        }
    print("Logging to file disabled.")
    return


def get_lh(level: str):
    """Create logtail handler"""
    if not bot_settings.logtail_token:
        return
    return {
        "class": "logtail.LogtailHandler",
        "source_token": bot_settings.logtail_token,
        # "flush_interval": 10,
        "host": "https://in.logs.betterstack.com",
        "formatter": JSONFORMAT_FORMATTER,
        "level": level,
    }


if FILE_HANDLER := get_fh(log_config.file.level):
    HANDLERS["file_handler"] = FILE_HANDLER
if LOGTAIL_HANDLER := get_lh(log_config.level):
    HANDLERS["logtail_handler"] = LOGTAIL_HANDLER


# basic logging config
logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            JSONFORMAT_FORMATTER: {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.processors.JSONRenderer(),
                "foreign_pre_chain": BASE_PREPROCESSORS,
            },
            CONSOLE_FORMATTER: {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.dev.ConsoleRenderer(colors=True),
                "foreign_pre_chain": BASE_PREPROCESSORS,
            },
        },
        "handlers": HANDLERS,
        "loggers": {
            "": {
                "handlers": (
                    [
                        CONSOLE_HANDLER if sys.stderr.isatty() else JSONFORMAT_HANDLER,
                        "file_handler",
                        "logtail_handler",
                    ]
                    if FILE_HANDLER
                    else [
                        CONSOLE_HANDLER if sys.stderr.isatty() else JSONFORMAT_HANDLER,
                        "logtail_handler",
                    ]
                ),
                "level": log_config.level,
                "propagate": True,
            }
        },
    },
)

# structlog configuration
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(log_config.level),
    context_class=dict,
    processors=EXTENDED_PREPROCESSORS,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


# get root logger
root_log = structlog.get_logger()


# setup loggers
def setup_loggers():
    for module in log_settings.lib:
        logger = logging.getLogger(module.name)
        if module.enable:
            logger.setLevel(module.level)
        else:
            logger.propagate = False


setup_loggers()

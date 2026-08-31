"""Upload module"""

import base64

from pathlib import Path

# http requests
import httpx

# parse json
import msgspec

# structured logging
import structlog

# telegram core bot api extension
from telegram.ext import Application

# get log filename
from yoiyoi.extra.loggers import get_log_filename

# retry requests
from yoiyoi.extra.request_retriers import retry_request

# settings
from yoiyoi.extra.settings import bot_settings, log_settings

# setup logger
log = structlog.get_logger(__name__)


@retry_request
async def upload_to_cloud(file: Path, link: str) -> None:
    """Upload log file to Google Drive

    Args:
        file (Path): log file to upload
        link (str): upload link
    """
    log.info("Uploading log file %r...", file.name)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url=link,
            params={"name": file.name},
            content=base64.urlsafe_b64encode(file.read_bytes()),
            follow_redirects=True,
        )
        if msgspec.json.decode(response.content)["ok"]:
            log.info("Done uploading log file %r.", file.name)
        else:
            log.info("Log file %r already exists.", file.name)


async def upload_log(_: Application) -> None:
    """Upload log file"""
    if not log_settings.file.enable:
        log.error("No logging to file!")
        return
    if not (link := bot_settings.gd_log):
        log.error("No log upload link.")
        return
    if (file := get_log_filename()).exists():
        try:
            await upload_to_cloud(file, link)
        except httpx.ConnectTimeout:
            log.error("Error: No connection.")
        except msgspec.DecodeError:
            log.error("Couldn't upload log file %r.", file.name)

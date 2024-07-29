"""Upload module"""

import base64
import logging
import os

from pathlib import Path

# http requests
import httpx

# parse json
import orjson

# telegram core bot api extension
from telegram.ext import Application

# logger file handler
from ..extra.loggers import FILE_HANDLER

# retry requests
from ..extra.request_helpers import retry_request

# setup logger
log = logging.getLogger(__name__)


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
            data=base64.urlsafe_b64encode(file.read_bytes()),
            follow_redirects=True,
        )
        if orjson.loads(response.content)["ok"]:
            log.info("Done uploading log file %r.", file.name)
        else:
            log.info("Log file %r already exists.", file.name)


async def upload_log(_: Application) -> None:
    """Upload log file"""
    if not FILE_HANDLER:
        log.error("No such file!")
        return
    if not (link := os.environ.get("GD_LOG", None)):
        log.error("No log upload link.")
        return
    if (file := Path(FILE_HANDLER.baseFilename)).exists():
        try:
            await upload_to_cloud(file, link)
        except httpx.ConnectTimeout:
            log.error("Error: No connection.")
        except orjson.JSONDecodeError:
            log.error("Couldn't upload log file %r.", file.name)

"""Web Application"""

import re

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

# file extension check
import magic

# structured logging
import structlog

# web application
from fastapi import FastAPI, Request, Response, UploadFile

# web responses
from fastapi.responses import JSONResponse

# contextvars
from structlog.contextvars import bind_contextvars, unbind_contextvars

# telegram core bot api
from telegram import Update

# app strings
from yoiyoi.app import IM_FMT, VI_FMT

# the bot
from yoiyoi.app.bot import bot_application

# app utils
from yoiyoi.app.utils import convert_media_file, request_space, resize_image_file

# get image info
from yoiyoi.db.getters import get_info_by_identifier

# bot settings
from yoiyoi.extra.settings import bot_settings

# twitter api
from yoiyoi.services.twitter.api import get_twitter_links

# get logger
log = structlog.get_logger(__name__)

INTERNAL_PORT = 5001
PUBLIC_BASE_URL = f"https://{bot_settings.hook_url}/{bot_settings.token}/memory"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the background TUI process"""
    log.info("Starting API server...")
    yield
    log.info("Shutting down API server...")


# Initialize FastAPI with the lifespan handler
api_application = FastAPI(lifespan=lifespan)

ok_response = {
    "status": "ok",
    "info": "I'm fine.",
}

telegram_response = {
    "status": "ok",
    "info": "Added the update to the queue.",
}

failed_api_request = {
    "status": "failed",
    "info": "Wrong API key.",
}


@api_application.get("/health_check")
async def health():
    return JSONResponse(ok_response)


@api_application.post("/get_tweet")
async def get_tweet(api_key: str, tweet_id: int):
    bind_contextvars(update_id=f"api-{int(datetime.now().timestamp()) % 10000}")
    log.info("Got Twitter API key request.")
    if api_key == bot_settings.api_key:
        log.info("API key is correct. Trying to get tweet...")
        tweet_json = await get_twitter_links(tweet_id, json=True)
        log.info("Tweet: %s.", tweet_json)
        response = JSONResponse(tweet_json)
    else:
        log.info("API key is incorrect.")
        response = JSONResponse(failed_api_request)
    unbind_contextvars("update_id")
    return response


@api_application.post(f"/{bot_settings.token}")
async def telegram(request: Request):
    await bot_application.update_queue.put(
        Update.de_json(
            data=await request.json(),
            bot=bot_application.bot,
        )
    )
    return JSONResponse(telegram_response)


@api_application.post("/resize_for_telegram")
async def resize_for_telegram(upload_file: UploadFile | None = None):
    async with request_space() as (folder, unique_id):
        payload = {"id": unique_id}
        if not upload_file:
            return {**payload, "message": "No upload file sent!"}
        file = upload_file.file
        ext = magic.from_buffer(file.read(1024), mime=True)
        if ext.split("/")[1] not in IM_FMT:
            return {**payload, "message": f"Wrong content type: {ext}."}

        file.seek(0)
        image_file = folder / f'image.{ext.split("/")[1]}'
        image_file.write_bytes(file.read())

        file_out, send_type, error_text = await resize_image_file(image_file, ext)

        if error_text:
            return {**payload, "message": f"Error: {error_text}"}
        return Response(
            content=file_out.read_bytes(),
            media_type=send_type,
        )


@api_application.post("/convert_for_telegram")
async def convert_for_telegram(upload_file: UploadFile | None = None):
    async with request_space() as (folder, unique_id):
        payload = {"id": unique_id}
        if not upload_file:
            return {**payload, "message": "No upload file sent!"}
        file = upload_file.file
        ext = magic.from_buffer(file.read(1024), mime=True)
        if ext.split("/")[1] not in (IM_FMT | VI_FMT):
            return {**payload, "message": f"Wrong content type: {ext}."}

        file.seek(0)
        media_file = folder / f'media.{ext.split("/")[1]}'
        media_file.write_bytes(file.read())

        media_out, send_type, error_text = convert_media_file(media_file, ext)

        if error_text:
            return {**payload, "message": f"Error: {error_text}"}
        return Response(
            content=media_out.read_bytes(),
            media_type=send_type,
        )


ARTWORK_TYPES = {
    0: {
        "name": "twitter",
        "url_template": "https://twitter.com/i/status/{aid}",
    },
    1: {
        "name": "pixiv",
        "url_template": "https://www.pixiv.net/artworks/{aid}",
    },
}

IDENTIFIER_PATTERNS = [
    ("pixiv", re.compile(r"(?P<id>\d+)_p\d+(?:\.[a-z]{3,4})?", re.IGNORECASE)),
    ("twitter", re.compile(r"(?P<id>[\w\-]{15})(?:\.[a-z]{3,4})?", re.IGNORECASE)),
]


def extract_identifier(filename: str) -> tuple[Optional[str], Optional[str]]:
    """Extracts identifier and source platform from a filename.

    Returns:
        tuple[identifier, platform_name] or (None, None) if unmatched.
    """
    clean_filename = filename
    log.debug("Analyzing filename for patterns", filename=clean_filename)

    for platform, pattern in IDENTIFIER_PATTERNS:
        if match := pattern.search(clean_filename):
            extracted_id = match.group("id")
            log.info(
                "Successfully extracted identifier",
                platform=platform,
                extracted_id=extracted_id,
            )
            return extracted_id, platform

    log.debug("Filename did not match any known pattern", filename=clean_filename)
    return None, None


def format_artwork_data(row: dict) -> dict:
    """Formats raw database row into an artwork dictionary with platform metadata."""
    artwork_type = row.get("type")
    aid = row.get("aid")

    meta = ARTWORK_TYPES.get(artwork_type, {"name": "unknown", "url_template": None})
    template = meta["url_template"]

    return {
        "type": artwork_type,
        "type_name": meta["name"],
        "aid": aid,
        "link": template.format(aid=aid) if template and aid else None,
    }


@api_application.get("/get_image_info")
async def get_image_info(filename: str):
    bind_contextvars(update_id=f"api-{int(datetime.now().timestamp()) % 10000}")
    log.info("Received image info request", filename=filename)

    try:
        # 1. Parse Identifier
        identifier, platform = extract_identifier(filename)

        if not identifier:
            log.warning("Identifier extraction failed", filename=filename)
            return JSONResponse(
                status_code=400,
                content={
                    "status": "failed",
                    "info": (
                        f"Filename '{filename}' does not match recognized "
                        "pixiv or twitter patterns."
                    ),
                },
            )

        # 2. Query Database
        log.info(
            "Executing database query", identifier=identifier, detected_platform=platform
        )
        rows = await get_info_by_identifier(identifier=identifier)
        log.info("Database query returned results", row_count=len(rows))

        # 3. Format Response
        formatted_artworks = [format_artwork_data(row) for row in rows]
        log.debug(
            "Formatted response data successfully", artwork_count=len(formatted_artworks)
        )

        return JSONResponse(
            {
                "status": "ok",
                "extracted_id": identifier,
                "artworks": formatted_artworks,
            }
        )

    except Exception as exc:
        log.error(
            "Unhandled error processing request",
            filename=filename,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "info": f"Database error: {exc}"},
        )

    finally:
        unbind_contextvars("update_id")

"""Web Application"""

from contextlib import asynccontextmanager
from datetime import datetime

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

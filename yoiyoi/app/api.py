"""Web Application"""

import asyncio

from contextlib import asynccontextmanager
from datetime import datetime

# http requests
import httpx

# file extension check
import magic

# structured logging
import structlog

# websockets
import websockets

# web application
from fastapi import FastAPI, Request, Response, UploadFile, WebSocket

# web responses
from fastapi.responses import HTMLResponse, JSONResponse

# contextvars
from structlog.contextvars import bind_contextvars, unbind_contextvars

# telegram core bot api
from telegram import Update

# textual server
from textual_serve.server import Server

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
    log.info("Starting internal Textual server for Memray...")
    server = Server(
        "memray live 1337",
        host="127.0.0.1",
        port=INTERNAL_PORT,
        public_url=PUBLIC_BASE_URL,
    )
    tui_task = asyncio.create_task(asyncio.to_thread(server.serve))

    yield

    log.info("Shutting down TUI server...")
    tui_task.cancel()


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


@api_application.post("/resize_for_telegram/")
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


@api_application.post("/convert_for_telegram/")
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


@api_application.get(f"/{bot_settings.token}/memory")
async def proxy_textual_main(request: Request):
    """Proxies the main HTML page of the TUI"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"http://127.0.0.1:{INTERNAL_PORT}/", timeout=2.0)
            return HTMLResponse(content=resp.text)
        except httpx.ConnectError:
            return HTMLResponse(
                content=(
                    "<h1>TUI Server is starting...</h1>"
                    "<p>Please refresh in 5 seconds.</p>"
                ),
                status_code=503,
            )


@api_application.get(f"/{bot_settings.token}/memory/static/{{path:path}}")
async def proxy_static(path: str):
    """Proxies CSS/JS/Fonts"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://127.0.0.1:{INTERNAL_PORT}/static/{path}")
        return Response(content=resp.content, media_type=resp.headers.get("content-type"))


@api_application.websocket(f"/{bot_settings.token}/memory/ws")
async def websocket_proxy(websocket: WebSocket):
    """Proxies the terminal data stream"""
    await websocket.accept()
    async with websockets.connect(f"ws://127.0.0.1:{INTERNAL_PORT}/ws") as target_ws:

        async def forward_to_client():
            async for message in target_ws:
                await websocket.send_text(message)

        async def forward_to_server():
            async for message in websocket.iter_text():
                await target_ws.send(message)

        await asyncio.gather(forward_to_client(), forward_to_server())

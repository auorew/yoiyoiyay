"""Web Application"""

from datetime import datetime

# structured logging
import structlog

# web application
from fastapi import FastAPI, Request

# send json response
from fastapi.responses import JSONResponse
from structlog.contextvars import bind_contextvars

# telegram core bot api
from telegram import Update

# twitter api
from yoiyoi.api.twitter import get_twitter_links

# the bot
from yoiyoi.app.bot import bot_application
from yoiyoi.bot.filters import clear_context

# settings
from yoiyoi.extra.settings import bot_settings

# get logger
log = structlog.get_logger(__name__)

api_application = FastAPI()

ok_response = {
    "status": "ok",
    "info": "I'm fine.",
}

telegram_response = {
    "status": "ok",
    "info": "Added the update to the queue.",
}


@api_application.get("/health_check")
async def health():
    return JSONResponse(ok_response)


@api_application.post("/get_tweet")
@clear_context
async def get_tweet(api_key: str, tweet_id: int, request: Request):
    bind_contextvars({"update_id": f"api-{int(datetime.now().timestamp()) % 10000}"})
    if api_key == bot_settings.api_key:
        log.info("API key is correct. Trying to get tweet...")
        tweet_json = await get_twitter_links(tweet_id, json=True)
        log.info("Tweet: %s.", tweet_json)
        return JSONResponse(tweet_json)


@api_application.post(f"/{bot_settings.token}")
async def telegram(request: Request):
    await bot_application.update_queue.put(
        Update.de_json(
            data=await request.json(),
            bot=bot_application.bot,
        )
    )
    return JSONResponse(telegram_response)

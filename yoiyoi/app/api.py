"""Web Application"""

import logging

# web application
from fastapi import FastAPI, Request

# send json response
from fastapi.responses import JSONResponse

# telegram core bot api
from telegram import Update

# twitter api
from yoiyoi.api.twitter import get_twitter_links

# the bot
from yoiyoi.app.bot import bot_application

# settings
from yoiyoi.extra.settings import bot_settings

# get logger
log = logging.getLogger(__name__)

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
async def get_tweet(api_key: str, tweet_id: int):
    if api_key == bot_settings.api_key:
        return JSONResponse(await get_twitter_links(tweet_id, json=True))


@api_application.post(f"/{bot_settings.token}")
async def telegram(request: Request):
    await bot_application.update_queue.put(
        Update.de_json(
            data=await request.json(),
            bot=bot_application.bot,
        )
    )
    return JSONResponse(telegram_response)

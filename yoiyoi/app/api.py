"""Web Application"""
import logging
import os

from fastapi import FastAPI, Request

# telegram core bot api
from telegram import Update

# twitter api
from ..api.twitter import get_twitter_links

# the bot
from .bot import bot_application

# get logger
log = logging.getLogger(__name__)

api_application = FastAPI()


@api_application.get("/health_check")
async def health():
    return "The bot is running fine."


@api_application.post("/get_tweet")
async def get_tweet(api_key: str, tweet_id: int):
    if api_key == os.environ["API_KEY"]:
        return await get_twitter_links(tweet_id, json=True)


@api_application.post(f'/{os.environ["TOKEN"]}')
async def telegram(request: Request):
    await bot_application.update_queue.put(
        Update.de_json(
            data=await request.json(),
            bot=bot_application.bot,
        )
    )
    return "The bot added the update to the queue."

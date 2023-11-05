import os

# pyrogram client
from pyrogram import Client

pyro_app = Client(
    "yoiyoibot",
    api_id=os.environ["API_ID"],
    api_hash=os.environ["API_HASH"],
    bot_token=os.environ["TOKEN"],
)

"""Program module"""

# pyrogram client
from pyrogram import Client

# settings
from yoiyoi.extra.settings import bot_settings

pyro_app = Client(
    "yoiyoibot",
    api_id=bot_settings.api_id,
    api_hash=bot_settings.api_hash,
    bot_token=bot_settings.token,
)

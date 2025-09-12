"""Program module"""

# pyrogram client
from pyrogram.client import Client

# settings
from yoiyoi.extra.settings import bot_settings

if bot_settings.api_id == 0 or bot_settings.api_hash == "" or bot_settings.token == "":
    raise RuntimeError("Telegram API ID, API hash and bot token all should be set.")

pyro_app = Client(
    "yoiyoibot",
    api_id=bot_settings.api_id,
    api_hash=bot_settings.api_hash,
    bot_token=bot_settings.token,
)

"""Services registry"""

from yoiyoi.services.pixiv.sender import PixivSender
from yoiyoi.services.tiktok.sender import TikTokSender
from yoiyoi.services.twitter.sender import TwitterSender
from yoiyoi.services.youtube_short.sender import YouTubeShortSender

__all__ = [
    "TikTokSender",
    "TwitterSender",
    "PixivSender",
    "YouTubeShortSender",
]

"""YouTube Short API"""

import asyncio
import re
import time

from io import StringIO
from typing import Optional

# parse json
import msgspec

# structured logging
import structlog

# yt-dlp
import yt_dlp

# async caching
from aiocache import cached

# decrypting
from cryptography.fernet import Fernet

# proxy
from yoiyoi.app.proxy import proxy_manager

# retry proxy max tries
from yoiyoi.extra import RETRY_PROXY_MAX_TRIES

# request helpers
from yoiyoi.extra.request_helpers import get_fake_headers

# retriers
from yoiyoi.extra.request_retriers import retry_request

# requests
from yoiyoi.extra.requests import get_content_size, make_request

# settings
from yoiyoi.extra.settings import bot_settings

# base opts
from yoiyoi.services.base import ytdlp_opts_base

# link types and other info
from yoiyoi.services.constants import LINKS

# YouTubeShortMedia namedtuple
from yoiyoi.services.namedtuples import Link, YouTubeShortContent, YouTubeShortMedia

# setup logger
log = structlog.get_logger(__name__)

# youtube short dictionary
YTSD = LINKS["youtube_short"]

# ISO 8601 duration parsing regex
duration_regex = re.compile(r"PT(?:(?P<H>\d+)H)?(?:(?P<M>\d+)M)?(?:(?P<S>\d+)S)?")

# yt-dlp options
ytdlp_ops = {
    **ytdlp_opts_base,
    "simulate": True,
    "forcejson": True,
}


# youtube API thumbnail quality
YT_QUALITY = ["maxres", "standard", "high", "medium", "default"]


def get_ytdlp_thumbnail(info: dict) -> dict:
    for quality in YT_QUALITY:
        if info.get(quality, None):
            return info[quality]["url"]


def parse_duration(duration: str):
    if duration and (parsed_duration := re.match(duration_regex, duration)):
        return sum(
            unit * mul
            for unit, mul in zip(
                map(lambda x: int(x) if x else 0, reversed(parsed_duration.groups())),
                (1, 60, 3600),
                strict=False,
            )
        )


async def get_youtube_info(link: Link) -> Optional[YouTubeShortMedia]:
    """Gets links from YouTube API.

    Args:
        link (Link): youtube short link.

    Returns:
        Optional[YouTubeShortMedia]: youtube info.
    """
    api_log = log.bind(api="ytapi.apps.mattw.io")
    base = "https://mattw.io"
    api = "https://ytapi.apps.mattw.io/v3/videos"
    if response := await make_request(
        url=api,
        method="GET",
        headers={**get_fake_headers(), "Origin": base},
        params={
            "key": "foo1",
            "quotaUser": "8zPW8L9nyFzpnJcTHFeFJWAGTxqssC3686F4wKoT",
            "part": "snippet,recordingDetails,status,contentDetails",
            "id": link.id,
            "_": int(time.time() * 1000),
        },
    ):
        # check response
        if response.is_error:
            return
        api_log.debug("Request to YouTube API succeeded.")
        try:
            info = msgspec.json.decode(response.content)
        except msgspec.DecodeError:
            api_log.warning("Couldn't decode json response: %r.", response.content)
            return
        api_log.debug("JSON: %r.", info)
        if not info["items"]:
            return
        info = info["items"][0]
        snippet = info["snippet"]
        return {
            "source": link.link,
            "id": link.id,
            "title": snippet["title"],
            "thumb": get_ytdlp_thumbnail(snippet["thumbnails"]),
            "desc": snippet["description"],
            "channel_name": snippet["channelTitle"],
            "channel_id": snippet["channelId"],
            "duration": parse_duration(info["contentDetails"]["duration"]),
        }


@cached(
    ttl=15,
    key_builder=lambda fn, *a, **kw: a[0],
    skip_cache_func=lambda r: r is None,
)
@retry_request
async def get_ytdlp_with_proxy(link: str):
    api_log = log.bind(api="yt-dlp")
    use_proxy = (
        proxy_manager.active and proxy_manager.request_attempts <= RETRY_PROXY_MAX_TRIES
    )
    current_proxy = proxy_manager.active if use_proxy else None

    def _extract():
        with yt_dlp.YoutubeDL(
            {
                **ytdlp_ops,
                "cookiefile": StringIO(
                    Fernet(bot_settings.yt_key)
                    .decrypt(bot_settings.yt_cookies.encode())
                    .decode()
                ),
                "proxy": current_proxy,
            }
        ) as ytdl:
            return ytdl.extract_info(link, download=False)

    try:
        info = await asyncio.to_thread(_extract)
        proxy_manager.reset_attempts()
        return info

    except Exception as exception:
        api_log.warning(
            "yt-dlp: Failed because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            link=link,
        )
        raise


async def get_ytdlp_links(link: Link) -> list[Optional[YouTubeShortContent]]:
    """Gets links from YT-DLP.

    Args:
        link (Link): youtube short link.

    Returns:
        list[Optional[YouTubeShortContent]]: youtube short content namedtuple.
    """
    api_log = log.bind(api="yt-dlp")
    content = []
    try:
        if not (info := await get_ytdlp_with_proxy(link.link)):
            api_log.warning("Got no data from yt-dlp!")
            return content
        videos = []
        for video_format in info["formats"]:
            if video_format["vcodec"] != "none" and video_format["acodec"] != "none":
                videos.append(video_format)
        for video in sorted(videos, key=lambda x: x["height"], reverse=True):
            if not (url := video.get("url")):
                continue
            content.append(
                YouTubeShortContent(
                    url,
                    (
                        video.get("filesize", 0)
                        or video.get("filesize_approx", 0)
                        or await get_content_size(
                            video["url"],
                            headers=video["http_headers"],
                        )
                        or 0
                    ),
                    video["http_headers"],
                    {},
                )
            )
    except Exception as exception:
        api_log.warning(
            "yt-dlp: Failed because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            link=link,
        )
    return content


async def get_youtube_short_links(link: Link) -> Optional[YouTubeShortMedia]:
    """Gets youtube short links.

    Args:
        link (Link): youtube short link.

    Returns:
        Optional[YouTubeShortMedia]: youtube media namedtuple.
    """
    if not (info := await get_youtube_info(link)):
        return

    log.info("YouTube Short info: %s.", info)

    for get_links in (get_ytdlp_links,):  # best
        if ytsc := await get_links(link):
            return YouTubeShortMedia(**info, content=ytsc)
        log.info("Trying another API...")
    else:
        return

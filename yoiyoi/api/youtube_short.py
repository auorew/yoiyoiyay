"""YouTube Short module"""

import re
import time

from io import StringIO
from typing import Optional

# parse json
import orjson

# structured logging
import structlog

# yt-dlp
import yt_dlp

# beautiful soup
from bs4 import BeautifulSoup

# decrypting
from cryptography.fernet import Fernet

# link types and other info
from yoiyoi.api import LINKS

# YouTubeShortMedia namedtuple
from yoiyoi.api.namedtuples import Link, YouTubeShortContent, YouTubeShortMedia

# any extra data
from yoiyoi.extra import PROXY, PROXY_SET

# fake headers and request helpers
from yoiyoi.extra.request_helpers import FAKE_HEADERS, get_content_size, make_request

# settings
from yoiyoi.extra.settings import bot_settings

# setup logger
log = structlog.get_logger(__name__)

# youtube short dictionary
YTSD = LINKS["youtube_short"]

# ISO 8601 duration parsing regex
duration_regex = re.compile(r"PT(?:(?P<H>\d+)H)?(?:(?P<M>\d+)M)?(?:(?P<S>\d+)S)?")

# yt-dlp options
ytdlp_ops = {
    "quiet": True,
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
    base = "https://mattw.io"
    api = "https://ytapi.apps.mattw.io/v3/videos"
    if response := await make_request(
        url=api,
        method="GET",
        headers={**FAKE_HEADERS, "Origin": base},
        params={
            "key": "foo1",
            "quotaUser": "8zPW8L9nyFzpnJcTHFeFJWAGTxqssC3686F4wKoT",
            "part": "snippet,recordingDetails,status,contentDetails",
            "id": link.id,
            "_": int(time.time() * 1000),
        },
        timeout=5,
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", info)
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


async def get_ytdlp_with_proxy(link: Link):
    attempt = 0
    while attempt < 5:
        if not PROXY["active"]:
            if PROXY_SET:
                PROXY["active"] = PROXY_SET.pop()
        try:
            with yt_dlp.YoutubeDL(
                {
                    **ytdlp_ops,
                    "cookiefile": StringIO(
                        Fernet(bot_settings.yt_key)
                        .decrypt(bot_settings.yt_cookies.encode())
                        .decode()
                    ),
                    "proxy": PROXY["active"] if PROXY["active"] else None,
                }
            ) as ytdl:
                return ytdl.extract_info(link.link)
        except Exception as exception:
            attempt += 1
            log.warning(
                "yt-dlp: Failed because of %s: %r.",
                exception.__class__.__name__,
                exception,
                exc_info=True,
                # function info
                link=link,
            )
            if not PROXY_SET:
                PROXY["active"] = None
                return
            else:
                PROXY["active"] = PROXY_SET.pop()


async def get_ytdlp_links(link: Link) -> list[Optional[YouTubeShortContent]]:
    """Gets links from YT-DLP.

    Args:
        link (Link): youtube short link.

    Returns:
        list[Optional[YouTubeShortContent]]: youtube short content namedtuple.
    """
    content = []
    try:
        if not (info := await get_ytdlp_with_proxy(link)):
            log.warning("Got no data from yt-dlp!")
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
                    video.get("filesize", 0) or video.get("filesize_approx", 0) or 0,
                )
            )
    except Exception as exception:
        log.warning(
            "yt-dlp: Failed because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            link=link,
        )
    return content


async def get_10downloader_links(link: Link) -> list[Optional[YouTubeShortContent]]:
    """Gets links from 10downloader.

    Args:
        link (Link): youtube short link.

    Returns:
        list[Optional[YouTubeShortContent]]: youtube short content namedtuple.
    """
    log.info("API: 10downloader.")
    content = []
    # api info
    base = "https://10downloader.com/en/73"
    api = "https://10downloader.com/download"
    # send request
    if response := await make_request(
        api,
        method="GET",
        xsrf="XSRF-TOKEN",
        referer=base,
        params={
            "v": link.link,
            "lang": "en",
            "type": "video",
        },
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        # process response
        soup = BeautifulSoup(response.content, "html.parser")
        for download_link in soup.find_all("a", class_="downloadBtn")[:2]:
            if download_link["download"].endswith("mp4"):
                if (_size := await get_content_size(_link := download_link["href"])) > 0:
                    content.append(YouTubeShortContent(_link, _size))
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

    for get_links in (
        get_ytdlp_links,  # best
        get_10downloader_links,  # good
    ):
        if ytsc := await get_links(link):
            return YouTubeShortMedia(**info, content=ytsc)
        log.info("Trying another API...")
    else:
        return

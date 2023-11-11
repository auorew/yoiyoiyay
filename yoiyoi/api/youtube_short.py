"""YouTube Short module"""
import logging
import re
import time

from typing import Optional

# parse json
import orjson

# yt-dlp
import yt_dlp

# beautiful soup
from bs4 import BeautifulSoup

# link types and other info
from ..api import LINKS

# YouTubeShortMedia namedtuple
from ..api.namedtuples import Link, YouTubeShortContent, YouTubeShortMedia

# fake headers and request helpers
from ..extra.request_helpers import FAKE_HEADERS, get_file_size, make_request

# setup logger
log = logging.getLogger(__name__)

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
    api = "https://www.googleapis.com/youtube/v3/videos"
    if response := await make_request(
        url=api,
        method="GET",
        headers={**FAKE_HEADERS, "Origin": base},
        params={
            "key": "AIzaSyASTMQck-jttF8qy9rtEnt1HyEYw5AmhE8",
            "quotaUser": "eF6wx17mAsvONQ9fcwfCA7IdXCoMe2TytRSZqzgL",
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
            "thumb": snippet["thumbnails"]["maxres"]["url"],
            "desc": snippet["description"],
            "channel_name": snippet["channelTitle"],
            "channel_id": snippet["channelId"],
            "duration": parse_duration(info["contentDetails"]["duration"]),
        }


async def get_ytdlp_links(link: Link) -> list[Optional[YouTubeShortContent]]:
    """Gets links from YTShorts.

    Args:
        link (Link): youtube short link.

    Returns:
        list[Optional[YouTubeShortContent]]: youtube short content namedtuple.
    """
    content = []
    with yt_dlp.YoutubeDL(ytdlp_ops) as ytdl:
        info = ytdl.extract_info(link.link)
        videos = []
        for video_format in info["formats"]:
            if video_format["vcodec"] != "none" and video_format["acodec"] != "none":
                videos.append(video_format)
        for video in sorted(videos, key=lambda x: x["height"], reverse=True):
            content.append(
                YouTubeShortContent(
                    video["url"],
                    video["filesize"] or video["filesize_approx"] or 0,
                )
            )
    return content


async def get_ytshorts_links(link: Link) -> list[Optional[YouTubeShortContent]]:
    """Gets links from YTShorts.

    Args:
        link (Link): youtube short link.

    Returns:
        list[Optional[YouTubeShortContent]]: youtube short content namedtuple.
    """
    log.info("API: YTShorts.")
    content = []
    # api info
    base = "https://ytshorts.savetube.me/"
    api = "https://cdn2.savetube.me/info"
    # send request
    if response := await make_request(
        url=api,
        method="GET",
        headers={**FAKE_HEADERS, "Referer": base},
        params={"url": link.link},
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
        if not info["status"]:
            log.warning("Couldn't get content.")
            return
        # process response
        videos = info["data"]["video_formats"][1:]
        for video in filter(lambda video: video.get("url"), videos):
            _link = video["url"]
            content.append(YouTubeShortContent(_link, await get_file_size(_link)))
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
                if (_size := await get_file_size(_link := download_link["href"])) > 0:
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
        get_ytshorts_links,  # good
        get_10downloader_links,  # good
    ):
        if ytsc := await get_links(link):
            return YouTubeShortMedia(**info, content=ytsc)
        log.info("Trying another API...")
    else:
        return

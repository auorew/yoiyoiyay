"""Xiaohongshu module"""

import asyncio

from http.cookies import SimpleCookie
from typing import Optional

# json parsing
import orjson

# structured logging
import structlog

# yt-dlp
import yt_dlp

# async caching
from aiocache import cached

# TikTokVideo namedtuple
from yoiyoi.api.namedtuples import XiaohongshuMedia, XiaohongshuVideo

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

# setup logger
log = structlog.get_logger(__name__)

# yt-dlp options
ytdlp_ops = {
    "quiet": True,
    "simulate": True,
    "forcejson": True,
}


@cached(
    ttl=15,
    key_builder=lambda fn, *a, **kw: a[0],
    skip_cache_func=lambda r: r is None,
)
@retry_request
async def get_ytdlp_info(link: str) -> dict:
    """Gets xhs info from yt-dlp.

    Args:
        link (str): formatted xhs link.

    Returns:
        dict: xhs info.
    """
    api_log = log.bind(api="yt-dlp")
    use_proxy = (
        proxy_manager.active and proxy_manager.request_attempts <= RETRY_PROXY_MAX_TRIES
    )
    current_proxy = proxy_manager.active if use_proxy else None

    def _extract():
        with yt_dlp.YoutubeDL({**ytdlp_ops, "proxy": current_proxy}) as ytdl:
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


async def get_info_ytdlp(link: str) -> dict:
    """Gets basic tiktok info from yt-dlp.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    log.info("Info: YouTube-DLP.")
    if info := await get_ytdlp_info(link):
        log.debug("yt-dlp info.", info=info)
        return info


async def get_links_ytdlp(link):
    log.info("API: YouTube-DLP.")

    if not (info := await get_info_ytdlp(link)):
        return

    if not (thumbnails := info.get("thumbnails")):
        log.error("No thumbnail.")
        return

    max_size = 0
    largest_thumbnail = None
    for thumbnail in thumbnails:
        if (size := await get_content_size(thumbnail["url"])) >= max_size:
            max_size = size
            largest_thumbnail = thumbnail["url"]

    if not largest_thumbnail:
        log.error("No largest thumbnail?!")
        return

    result = {
        "title": info["title"],
        "description": info["description"],
        "thumb": largest_thumbnail,
    }

    videos = []
    for video_format in info["formats"]:
        if (
            video_format.get("height")
            and video_format.get("vcodec")
            and video_format.get("vcodec") != "none"
            and video_format.get("acodec")
            and video_format.get("acodec") != "none"
        ):
            videos.append(video_format)

    result["content"] = []
    for video in sorted(videos, key=lambda x: x["filesize"], reverse=True):
        cookies = {}
        if video_cookies := video.get("cookies"):
            log.info("Cookies found!")
            cookie = SimpleCookie()
            cookie.load(video_cookies)
            cookies = {key: morsel.value for key, morsel in cookie.items()}
        else:
            log.info("No cookies found!")
        headers: dict = video["http_headers"]
        extra = {"cookies": cookies, "headers": headers}
        # if _ext := await get_content_extension(video["url"], **extra):
        #     log.info("Video extension: %s.", _ext)
        #     if _ext == "html":
        #         log.warning("Can't download video in html format.")
        #         continue
        if (
            _size := video.get("filesize")
            or video.get("filesize_approx")
            or await get_content_size(
                video["url"],
                **extra,
            )
        ):
            result["content"].append(
                {
                    "link": video["url"],
                    "size": _size,
                    "extra": extra,
                }
            )

    return result


async def get_links_seekin(link):
    log.info("API: Seekin AI.")

    result = {}
    if (
        response := await make_request(
            "https://api.seekin.ai/ikool/media/download",
            headers={
                **get_fake_headers(),
                "Accept": "*/*",
                "Referer": "https://www.seekin.ai/",
                "Content-Type": "application/json",
                "Origin": "https://www.seekin.ai",
                "DNT": "1",
                "Sec-GPC": "1",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Priority": "u=0",
            },
            json={"url": link},
        )
    ).is_error:
        log.info("No response.")
        return
    try:
        info = orjson.loads(response.content)
    except orjson.JSONDecodeError:
        log.warning("Couldn't decode json response: %r.", response.content)
        return

    if not (code := info.get("code", "")) or code != "0000":
        log.warning("No success code found: %r.", code)
        return

    if not (data := info.get("data", "")):
        log.warning("No success code found: %r.", info["code"])
        return

    if "|||" in data["title"]:
        result["title"], result["description"] = data["title"].split("|||")
    else:
        result["title"], result["description"] = data["title"], ""
    result["thumb"] = data["imageUrl"]
    result["content"] = []
    for media in data["medias"]:
        video = {}
        video["link"] = media["url"]
        video["size"] = media["fileSize"]
        video["extra"] = {}
        result["content"].append(video)

    return result


async def convert_dictionary_to_namedtuple(
    result: dict[str, str | int],
) -> XiaohongshuMedia:
    content = []
    for video_dict in result["content"]:
        video_tuple = XiaohongshuVideo(
            link=video_dict["link"],
            size=video_dict["size"],
            extra=video_dict["extra"],
        )
        content.append(video_tuple)

    media = XiaohongshuMedia(
        id=result["id"],
        source=result["source"],
        title=result["title"],
        description=result["description"],
        thumb=result["thumb"],
        content=content,
    )

    return media


async def get_xiaohongshu_links(link: str) -> Optional[XiaohongshuMedia]:
    """Gets xiaohongshu links.

    Args:
        link (str): xiaohongshu link.

    Returns:
        Optional[XiaohongshuMedia]: full xiaohongshu info.
    """
    data = {
        "id": link.rsplit("/")[-1],
        "source": link,
    }
    for get_links in (
        get_links_ytdlp,  # good
        get_links_seekin,  # good
    ):
        if result := await get_links(link):
            return await convert_dictionary_to_namedtuple({**data, **result})
        log.info("Trying another API...")
    else:
        log.error("Couldn't get content.")
        return

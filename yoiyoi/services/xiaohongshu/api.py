"""Xiaohongshu API"""

import asyncio

from http.cookies import SimpleCookie
from typing import List, Optional

# parse json
import msgspec

# structured logging
import structlog

# yt-dlp
import yt_dlp

# async caching
from aiocache import cached

# proxy
from yoiyoi.app.proxy import proxy_manager

# retry proxy max tries
from yoiyoi.extra import RETRY_PROXY_MAX_TRIES

# retriers
from yoiyoi.extra.request_retriers import retry_request

# requests
from yoiyoi.extra.requests import get_content_size

# settings
from yoiyoi.extra.settings import bot_settings

# service helpers
from yoiyoi.services.helpers import fetch_api_json

# Xiaohongshu namedtuples
from yoiyoi.services.namedtuples import (
    XiaohongshuMedia,
    XiaohongshuPhoto,
    XiaohongshuVideo,
)

# setup logger
log = structlog.get_logger(__name__)


class XHSImageDetail(msgspec.Struct):
    url: str


class XHSNoteData(msgspec.Struct):
    id: str
    title: Optional[str] = ""
    desc: Optional[str] = ""
    author: Optional[str] = ""
    type: str  # "image" or "video"
    image_list: List[XHSImageDetail] = []
    video_url: Optional[str] = None


class XHSApiResponse(msgspec.Struct):
    code: int
    msg: str
    data: Optional[XHSNoteData] = None


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


async def get_xhs_links(url: str) -> Optional[XHSApiResponse]:
    """Posts a Note URL to the XHS-Downloader container API."""
    payload = {
        "url": url,
        "download": False,  # Request direct media URLs without saving to container disk
        "check_record": False,
    }

    if bot_settings.xhs_cookie:
        payload["cookie"] = bot_settings.xhs_cookie

    response_data = await fetch_api_json(
        url=bot_settings.xhs_api_url,
        method="POST",
        json=payload,
        api_log=log,
    )

    if not response_data:
        return None

    try:
        return msgspec.json.decode(
            msgspec.json.encode(response_data), type=XHSApiResponse
        )
    except msgspec.DecodeError as e:
        log.warning("Failed to parse XHS container response.", error=str(e))
        return None


async def get_links_container(link: str) -> Optional[dict]:
    """Gets xiaohongshu content from the XHS-Downloader container API."""
    log.info("API: XHS-Downloader.")

    response = await get_xhs_links(link)
    if not response or not response.data:
        log.warning("XHS container returned no data.")
        return None

    data = response.data
    thumb = data.image_list[0].url if data.image_list else ""
    content = []

    if data.type == "video" and data.video_url:
        size = await get_content_size(data.video_url)
        content.append(
            XiaohongshuVideo(
                link=data.video_url,
                size=size,
                extra={},
            )
        )
    elif data.image_list:
        for img in data.image_list:
            size = await get_content_size(img.url)
            content.append(
                XiaohongshuPhoto(
                    link=img.url,
                    size=size,
                    extra={},
                )
            )

    if not content:
        log.error("No media content extracted from container response.")
        return None

    return {
        "id": data.id or link.rsplit("/")[-1],
        "title": data.title or "",
        "description": data.desc or "",
        "thumb": thumb,
        "content": content,
    }


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


async def convert_dictionary_to_namedtuple(
    result: dict,
) -> XiaohongshuMedia:
    content = []
    for item in result["content"]:
        if isinstance(item, (XiaohongshuVideo, XiaohongshuPhoto)):
            content.append(item)
        elif isinstance(item, dict):
            content.append(
                XiaohongshuVideo(
                    link=item["link"],
                    size=item["size"],
                    extra=item["extra"],
                )
            )

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
    for get_links in (get_links_container, get_links_ytdlp):  # fallback sequence
        if result := await get_links(link):
            return await convert_dictionary_to_namedtuple({**data, **result})
        log.info("Trying another API...")
    else:
        log.error("Couldn't get content.")
        return None

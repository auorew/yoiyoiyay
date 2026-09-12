"""Xiaohongshu API"""

import asyncio

from http.cookies import SimpleCookie
from typing import Optional

# http requests
import httpx

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


class XHSNoteData(msgspec.Struct, kw_only=True):
    id: str = msgspec.field(name="作品ID")
    title: Optional[str] = msgspec.field(default="", name="作品标题")
    desc: Optional[str] = msgspec.field(default="", name="作品描述")
    author: Optional[str] = msgspec.field(default="", name="作者昵称")
    note_type: str = msgspec.field(default="图文", name="作品类型")
    download_urls: Optional[list[str]] = msgspec.field(default=None, name="下载地址")
    cover: Optional[str] = msgspec.field(default=None, name="封面地址")


class XHSApiResponse(msgspec.Struct, kw_only=True):
    message: Optional[str] = None
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
        "download": False,
        "check_record": False,
    }

    if bot_settings.xhs_cookie:
        payload["cookie"] = bot_settings.xhs_cookie

    response_data = await fetch_api_json(
        url=bot_settings.xhs_api_url,
        method="POST",
        json=payload,
        timeout=httpx.Timeout(60.0, connect=10.0),
        api_log=log,
    )

    if not response_data:
        return None

    try:
        # Convert dictionary directly into msgspec struct
        return msgspec.structs.convert(response_data, XHSApiResponse)
    except (msgspec.ValidationError, TypeError) as e:
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
    urls = data.download_urls or []
    if not urls:
        log.error("No download URLs found in container response.")
        return None

    # Thumbnail fallback: use explicit cover or first media URL
    thumb = data.cover or urls[0]
    content = []

    if data.note_type == "视频":
        for video_url in urls:
            size = await get_content_size(video_url)
            content.append(
                XiaohongshuVideo(
                    link=video_url,
                    size=size,
                    extra={},
                )
            )
    else:  # "图文" (Image Carousel)
        for img_url in urls:
            size = await get_content_size(img_url)
            content.append(
                XiaohongshuPhoto(
                    link=img_url,
                    size=size,
                    extra={},
                )
            )

    return {
        "id": data.id,
        "title": data.title,
        "description": data.desc,
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


async def get_links_ytdlp(link: str) -> Optional[dict]:
    log.info("API: YouTube-DLP.")

    if not (info := await get_info_ytdlp(link)):
        return None

    if not (thumbnails := info.get("thumbnails")):
        log.error("No thumbnail.")
        return None

    max_size = 0
    largest_thumbnail = None
    for thumbnail in thumbnails:
        if (size := await get_content_size(thumbnail["url"])) >= max_size:
            max_size = size
            largest_thumbnail = thumbnail["url"]

    if not largest_thumbnail:
        log.error("No largest thumbnail?!")
        return None

    videos = []
    for video_format in info.get("formats", []):
        if (
            video_format.get("height")
            and video_format.get("vcodec")
            and video_format.get("vcodec") != "none"
            and video_format.get("acodec")
            and video_format.get("acodec") != "none"
        ):
            videos.append(video_format)

    content = []
    for video in sorted(videos, key=lambda x: x.get("filesize", 0) or 0, reverse=True):
        cookies = {}
        if video_cookies := video.get("cookies"):
            cookie = SimpleCookie()
            cookie.load(video_cookies)
            cookies = {key: morsel.value for key, morsel in cookie.items()}

        headers: dict = video.get("http_headers", {})
        extra = {"cookies": cookies, "headers": headers}

        if (
            _size := video.get("filesize")
            or video.get("filesize_approx")
            or await get_content_size(video["url"], **extra)
        ):
            content.append(
                {
                    "link": video["url"],
                    "size": _size,
                    "extra": extra,
                }
            )

    # yt-dlp only extracts videos; return None if no video formats were extracted
    if not content:
        log.warning("yt-dlp found no video content.")
        return None

    return {
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "thumb": largest_thumbnail,
        "content": content,
    }


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

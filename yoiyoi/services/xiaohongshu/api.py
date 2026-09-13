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
    api_log = log.bind(api="yt-dlp", link=link)
    use_proxy = (
        proxy_manager.active and proxy_manager.request_attempts <= RETRY_PROXY_MAX_TRIES
    )
    current_proxy = proxy_manager.active if use_proxy else None

    api_log.debug("Executing yt-dlp extraction.", proxy=current_proxy)

    def _extract():
        with yt_dlp.YoutubeDL({**ytdlp_ops, "proxy": current_proxy}) as ytdl:
            return ytdl.extract_info(link, download=False)

    try:
        info = await asyncio.to_thread(_extract)
        proxy_manager.reset_attempts()
        api_log.info(
            "yt-dlp extraction successful.", id=info.get("id"), title=info.get("title")
        )
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
    req_log = log.bind(api="XHS-Downloader", request_url=url)

    payload = {
        "url": url,
        "download": False,
        "check_record": False,
    }

    if bot_settings.xhs_cookie:
        payload["cookie"] = bot_settings.xhs_cookie
        req_log.debug("Using configured XHS cookie.")

    req_log.debug(
        "Sending request to container endpoint.",
        endpoint=bot_settings.xhs_api_url,
        payload=payload,
    )

    response_data = await fetch_api_json(
        url=bot_settings.xhs_api_url,
        method="POST",
        json=payload,
        timeout=httpx.Timeout(60.0, connect=10.0),
        api_log=log,
    )

    if not response_data:
        req_log.warning("Empty response received from XHS container.")
        return None

    req_log.debug(
        "Received raw response data from container.", raw_response=response_data
    )

    try:
        parsed = msgspec.convert(response_data, XHSApiResponse)
        req_log.info("Successfully converted container JSON to XHSApiResponse.")
        return parsed
    except (msgspec.ValidationError, TypeError) as e:
        req_log.warning(
            "Failed to parse XHS container response.",
            error=str(e),
            raw_response=response_data,
        )
        return None


async def get_links_container(link: str) -> Optional[dict]:
    """Gets xiaohongshu content from the XHS-Downloader container API."""
    container_log = log.bind(api="XHS-Downloader", link=link)
    container_log.info("Attempting extraction via XHS container.")

    response = await get_xhs_links(link)
    if not response or not response.data:
        container_log.warning("XHS container returned no valid data object.")
        return None

    data = response.data
    urls = data.download_urls or []

    container_log.debug(
        "Parsed note metadata from response.",
        note_id=data.id,
        title=data.title,
        author=data.author,
        note_type=data.note_type,
        urls_count=len(urls),
        has_explicit_cover=bool(data.cover),
    )

    if not urls:
        container_log.error("No download URLs found in note data.")
        return None

    thumb = data.cover or urls[0]
    container_log.debug(
        "Selected thumbnail URL.", thumb_url=thumb, is_fallback=not bool(data.cover)
    )

    content = []
    if data.note_type == "视频":
        container_log.info("Processing video note type.", url_count=len(urls))
        for idx, video_url in enumerate(urls, start=1):
            size = await get_content_size(video_url)
            container_log.debug(
                "Retrieved video stream size.", index=idx, url=video_url, size_bytes=size
            )
            content.append(
                XiaohongshuVideo(
                    link=video_url,
                    size=size,
                    extra={},
                )
            )
    else:  # "图文" (Image Carousel)
        container_log.info("Processing photo carousel note type.", photo_count=len(urls))
        for idx, img_url in enumerate(urls, start=1):
            size = await get_content_size(img_url)
            container_log.debug(
                "Retrieved photo size.", index=idx, url=img_url, size_bytes=size
            )
            content.append(
                XiaohongshuPhoto(
                    link=img_url,
                    size=size,
                    extra={},
                )
            )

    return {
        "id": data.id,
        "author": data.author or "",
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
    log.info("Fetching info via yt-dlp.", link=link)
    if info := await get_ytdlp_info(link):
        log.debug(
            "yt-dlp info retrieved successfully.",
            id=info.get("id"),
            formats_count=len(info.get("formats", [])),
        )
        return info


async def get_links_ytdlp(link: str) -> Optional[dict]:
    ytdlp_log = log.bind(api="YouTube-DLP", link=link)
    ytdlp_log.info("Attempting extraction via yt-dlp fallback.")

    if not (info := await get_info_ytdlp(link)):
        ytdlp_log.warning("yt-dlp returned no info dict.")
        return None

    thumbnails = info.get("thumbnails") or []
    if not thumbnails:
        ytdlp_log.error("No thumbnails available in yt-dlp info.")
        return None

    ytdlp_log.debug("Evaluating thumbnail candidates.", count=len(thumbnails))
    max_size = 0
    largest_thumbnail = None
    for thumbnail in thumbnails:
        size = await get_content_size(thumbnail["url"])
        if size >= max_size:
            max_size = size
            largest_thumbnail = thumbnail["url"]

    if not largest_thumbnail:
        ytdlp_log.error("Could not determine largest thumbnail.")
        return None

    ytdlp_log.debug(
        "Selected largest thumbnail.", url=largest_thumbnail, size_bytes=max_size
    )

    formats = info.get("formats", [])
    ytdlp_log.debug("Filtering video formats.", total_formats=len(formats))
    videos = []
    for video_format in formats:
        if (
            video_format.get("height")
            and video_format.get("vcodec")
            and video_format.get("vcodec") != "none"
            and video_format.get("acodec")
            and video_format.get("acodec") != "none"
        ):
            videos.append(video_format)

    ytdlp_log.debug("Filtered suitable video streams.", valid_videos_count=len(videos))

    content = []
    for video in sorted(videos, key=lambda x: x.get("filesize", 0) or 0, reverse=True):
        cookies = {}
        if video_cookies := video.get("cookies"):
            cookie = SimpleCookie()
            cookie.load(video_cookies)
            cookies = {key: morsel.value for key, morsel in cookie.items()}

        headers: dict = video.get("http_headers", {})
        extra = {"cookies": cookies, "headers": headers}

        _size = (
            video.get("filesize")
            or video.get("filesize_approx")
            or await get_content_size(video["url"], **extra)
        )
        if _size:
            content.append(
                {
                    "link": video["url"],
                    "size": _size,
                    "extra": extra,
                }
            )

    if not content:
        ytdlp_log.warning("yt-dlp found no usable video streams.")
        return None

    ytdlp_log.info("yt-dlp extraction successful.", content_items=len(content))
    return {
        "author": info.get("uploader")
        or info.get("channel")
        or info.get("creator")
        or "",
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "thumb": largest_thumbnail,
        "content": content,
    }


async def convert_dictionary_to_namedtuple(
    result: dict,
) -> XiaohongshuMedia:
    conv_log = log.bind(media_id=result.get("id"))
    content = []

    for idx, item in enumerate(result["content"], start=1):
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

    photos_count = sum(1 for x in content if isinstance(x, XiaohongshuPhoto))
    videos_count = sum(1 for x in content if isinstance(x, XiaohongshuVideo))

    conv_log.debug(
        "Converted raw result to XiaohongshuMedia.",
        total_items=len(content),
        photos=photos_count,
        videos=videos_count,
    )

    return XiaohongshuMedia(
        id=result["id"],
        source=result["source"],
        author=result.get("author", ""),
        title=result["title"],
        description=result["description"],
        thumb=result["thumb"],
        content=content,
    )


async def get_xiaohongshu_links(link: str) -> Optional[XiaohongshuMedia]:
    """Gets xiaohongshu links.

    Args:
        link (str): xiaohongshu link.

    Returns:
        Optional[XiaohongshuMedia]: full xiaohongshu info.
    """
    main_log = log.bind(target_link=link)
    main_log.info("Starting Xiaohongshu extraction workflow.")

    data = {
        "id": link.rsplit("/")[-1],
        "source": link,
    }

    for get_links in (get_links_container, get_links_ytdlp):
        func_name = get_links.__name__
        main_log.debug("Trying extraction strategy.", strategy=func_name)

        if result := await get_links(link):
            main_log.info("Extraction strategy succeeded.", strategy=func_name)
            return await convert_dictionary_to_namedtuple({**data, **result})

        main_log.warning(
            "Extraction strategy failed, attempting next provider.",
            failed_strategy=func_name,
        )
    else:
        main_log.error("All Xiaohongshu extraction strategies exhausted.")
        return None

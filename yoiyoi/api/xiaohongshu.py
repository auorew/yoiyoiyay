"""Xiaohongshu module"""

from http.cookies import SimpleCookie
from typing import Optional

# structured logging
import structlog

# yt-dlp
import yt_dlp

# async caching
from aiocache import cached

# TikTokVideo namedtuple
from yoiyoi.api.namedtuples import XiaohongshuMedia, XiaohongshuVideo

# proxy
from yoiyoi.extra import PROXY, PROXY_SET

# fake headers and request helpers
from yoiyoi.extra.request_helpers import (
    get_content_size,
)

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
async def get_ytdlp_info(link: str) -> dict:
    """Gets xhs info from yt-dlp.

    Args:
        link (str): formatted xhs link.

    Returns:
        dict: xhs info.
    """
    attempt = 0
    while attempt < 5:
        if not PROXY["active"]:
            if PROXY_SET:
                proxy_url = PROXY_SET.pop()
                log.info("Using proxy: %s.", proxy_url)
                PROXY["active"] = proxy_url
        try:
            with yt_dlp.YoutubeDL(
                {
                    **ytdlp_ops,
                    "proxy": PROXY["active"] if PROXY["active"] else None,
                }
            ) as ytdl:
                return ytdl.extract_info(link)

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
                proxy_url = PROXY_SET.pop()
                log.info("Using proxy: %s.", proxy_url)
                PROXY["active"] = proxy_url


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


async def get_xiaohongshu_links(link: str) -> Optional[XiaohongshuMedia]:
    """Gets xiaohongshu links.

    Args:
        link (str): xiaohongshu link.

    Returns:
        Optional[XiaohongshuMedia]: full xiaohongshu info.
    """
    log.info("API: YouTube-DLP.")
    if not (info := await get_info_ytdlp(link)):
        return

    if not (thumbnails := info.get("thumbnails")):
        log.error("No thumbnail.")
        return

    video_info = {
        "source": link,
        "id": info["id"],
        "title": info["title"],
        "description": info["description"],
        "uploader_id": info["uploader_id"],
        "webpage_url": info["webpage_url"],
        "thumb": thumbnails[0]["url"],
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

    content_videos = []
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
            content_videos.append(
                XiaohongshuVideo(
                    video["url"],
                    _size,
                    extra,
                )
            )

    return XiaohongshuMedia(**video_info, content=content_videos)

"""TikTok module"""

import asyncio
import json
import re

from http.cookies import SimpleCookie
from random import getrandbits
from typing import Optional

# parse json
import orjson

# structured logging
import structlog

# yt-dlp
import yt_dlp

# async caching
from aiocache import cached

# beautiful soup
from bs4 import BeautifulSoup

# hardcore retrying
from tenacity import stop_after_attempt

# link types and other info
from yoiyoi.api import LINKS, TikTokMediaKind

# deobfuscate js response
from yoiyoi.api.dehunter import dehunter

# TikTokVideo namedtuple
from yoiyoi.api.namedtuples import TikTokMedia, TikTokPhoto, TikTokVideo

# url expanders
from yoiyoi.api.urlexpander import expand_with_expandurl, expand_with_urlex

# fake headers and request helpers
from yoiyoi.extra.request_helpers import (
    FAKE_HEADERS,
    get_content_extension,
    get_content_name,
    get_content_size,
    make_request,
)

# setup logger
log = structlog.get_logger(__name__)

# tiktok thumbnail link
TT = LINKS["tiktok"]

# yt-dlp options
ytdlp_ops = {
    "quiet": True,
    "simulate": True,
    "forcejson": True,
}

# tiktok info typing
TikTokURL = str
TikTokSize = int

# tikmate link
TIKMATE_LINK = "https://tikmate.app/download/{0}/{1}.mp4{2}"

# regex
REGEX_TIKTOK_CDN = re.compile(r"(?P<name>\w+)~[\w\:\-]+\.(?P<extension>\w{3,4})")
REGEX_TIKMATE_IO = re.compile(r"tikmate-io_(?P<name>\w+)\.(?P<extension>\w{3,4})")
REGEX_SNAPTIK_APP = re.compile(r"snaptik_(?P<name>\w+)\.(?P<extension>\w{3,4})")
REGEX_COBALT_TOOLS = re.compile(
    r"\/(?P<name>[a-z0-9]+)~([a-z\-]+)\.(?P<extension>[^?]{3,4})"
)


def update_new(old_dict: dict, new_dict: dict):
    for key in tuple(old_dict):
        if old_dict[key] is None:
            del old_dict[key]
    for key in new_dict.keys() - old_dict.keys():
        old_dict[key] = new_dict[key]


@cached(
    ttl=15,
    key_builder=lambda fn, *a, **kw: a[0],
    skip_cache_func=lambda r: r is None,
)
async def get_ytdlp_info(link: str) -> dict:
    """Gets tiktok info from yt-dlp.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok info.
    """
    with yt_dlp.YoutubeDL(ytdlp_ops) as ytdl:
        try:
            return ytdl.extract_info(link)
        except yt_dlp.utils.DownloadError:
            log.warning("yt-dlp: Unable to download.")
            return
        except json.JSONDecodeError:
            log.warning("yt-dlp: Unable to decode.")
            return
        except Exception as exception:
            log.warning(
                "yt-dlp: Failed because of %s: %r.",
                exception.__class__.__name__,
                exception,
            )


async def get_tikmate_app_info(link: str) -> dict:
    """Gets tiktok info from TikMate.App.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    log.info("Info: TikMate App.")
    # api info
    base = "tikmate.app"
    api = f"https://api.{base}/api/lookup"
    # form request
    boundary = 29 * "-" + str(getrandbits(99))
    data = "\r\n".join(
        (
            boundary,
            'Content-Disposition: form-data; name="url"',
            "",
            link,
            boundary + "--\r\n",
        )
    )
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": f"multipart/form-data; boundary={boundary[2:]}",
            "Origin": f"https://{base}",
            "Referer": f"https://{base}/",
        },
        data=data,
        proxy=True,
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", info)
        if not info["success"]:
            log.warning("Couldn't find tiktok video.")
            return
        return info


async def get_basic_info_url_expand(link: str) -> dict:
    """Gets tiktok info from TikTok with URL expanders.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    log.info("Info: URL expanders.")
    for get_info in asyncio.as_completed(
        (
            expand_with_expandurl(link),  # good
            expand_with_urlex(link),  # okay
        )
    ):
        if (
            (url := await get_info)
            and (info := re.search(TT["info"], url))
            and info["author"] != "web"
        ):
            return {**info.groupdict(), "info_source": "urlexpander"}


async def get_basic_info_tiktok(link: str) -> dict:
    """Gets tiktok info from TikTok.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    log.info("Info: TikTok.")
    if (
        (response := await make_request(link, method="HEAD", proxy=True))
        and response.is_success
        and response.url.path != "/"
        and (info := re.search(TT["info"], response.url.path))
        and info["author"] != "web"
    ):
        log.debug("TikTok URL: %s.", response.url)
        return {**info.groupdict(), "info_source": "tiktok"}


async def get_basic_info_ytdlp(link: str) -> dict:
    """Gets basic tiktok info from yt-dlp.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    log.info("Info: YouTube-DLP.")
    if info := await get_ytdlp_info(link):
        log.debug("YouTube Basic Info: %r.", info)
        return {
            "id": int(info["id"], 0),
            "author": info["uploader"],
            "type": "photo" if info["video_ext"] == "none" else "video",
            "info_source": "yt-dlp",
        }


async def get_basic_info_downr(link: str) -> dict:
    """Gets basic tiktok info from downr.org.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    log.info("Info: downr.")
    api = "https://downr.org/.netlify/functions/download"
    if (
        response := await make_request(
            api,
            method="POST",
            headers={
                **FAKE_HEADERS,
                "Referer": "https://downr.org/",
                "Content-Type": "application/json",
                "Origin": "https://downr.org",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Priority": "u=0",
            },
            json={"url": link},
            follow_redirects=True,
            proxy=True,
        )
    ) and response.is_success:
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        if info["error"]:
            log.warning("downr returned error: %r.", response.content)
            return
        log.debug("downr info: %s.", info)
        tiktok_type = "video"
        if medias := info.get("medias"):
            for media in medias:
                if media.get("type") == "video":
                    tiktok_type = "video"
                    break
                elif media.get("type") == "image":
                    tiktok_type = "photo"
                    break
        return {
            "id": int(info.get("id", 0)),
            "author": info.get("unique_id"),
            "author_name": info.get("author"),
            "type": tiktok_type,
            "desc": info.get("title"),
            "thumb": info.get("thumbnail"),
            "info_source": "downr",
        }


async def get_basic_info_tikmate(link: str) -> dict:
    """Gets tiktok info from TikMate.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    if (info := await get_tikmate_app_info(link)) and info.get("success"):
        return {
            "id": int(info.get("id", 0)),
            "author": info.get("author_id"),
            "author_name": info.get("author_name"),
            "type": (
                "photo"
                if "photomode" in info.get("cover", "")
                or "photomode" in info.get("dynamic_cover", "")
                else "video"
            ),
            "thumb": info.get("cover"),
            "desc": info.get("desc"),
            "info_source": "tikmate.app",
        }


async def get_tiktok_thumbnail(basic_info: dict) -> dict:
    log.info("Advanced Info: TikTok Thumbnail.")
    if response := await make_request.retry_with(stop=stop_after_attempt(1))(
        url=f'https://www.tiktok.com/oembed?url={basic_info["source"]}',
        method="GET",
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", info)
        if info["author_name"] == "@":
            log.warning("TikTok Embed: Hidden content.")
            return
        # process response
        log.debug("TikTok Thumbnail Info: %r.", info)
        return {
            "thumb": info["thumbnail_url"],
            "author_name": info["author_name"],
            "desc": info["title"],
            "advinfo_source": "tiktok_embed",
        }


async def get_info_tokcounter(basic_info: dict) -> dict:
    """Gets advanced tiktok info from TokCounter.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
    log.info("Advanced Info: TokCounter.")
    # api info
    api = "https://tiktok.livecounts.io/video/download"
    # send request
    if response := await make_request.retry_with(stop=stop_after_attempt(1))(
        url=f"{api}/{basic_info['id']}",
        method="GET",
        headers={**FAKE_HEADERS, "Origin": "https://tokcounter.com"},
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", info)
        if not info["success"]:
            log.warning("Couldn't find tiktok video.")
            return
        # process response
        log.debug("TokCounter Info: %r.", info)
        return {
            "thumb": None,  # info['video']['cover'] is animated
            "author_name": info["author"]["name"],
            "desc": info["video"]["title"],
            "advinfo_source": "tokcounter",
        }


async def get_info_lovetik(basic_info: dict) -> dict:
    """Gets advanced tiktok info from LoveTik.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
    log.info("Advanced Info: LoveTik.")
    # api info
    base = "lovetik.com"
    api = f"https://{base}/api/ajax/search"
    # send request
    if response := await make_request.retry_with(stop=stop_after_attempt(1))(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded;" " charset=UTF-8",
            "Referer": f"https://{base}/",
        },
        # fallback source, since /photo/ URLs are not currently supported
        data={"query": basic_info["fallback"]},
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", info)
        if info["status"] != "ok" or info["mess"].startswith("Error"):
            log.warning("Couldn't find tiktok video.")
            return
        if info["author"] == "@":
            log.warning("TikTok Embed: Hidden content.")
            return
        # process response
        log.debug("LoveTik Info: %r.", info)
        return {
            "thumb": info["cover"],
            "author_name": info["author_name"],
            "desc": info["desc"],
            "advinfo_source": "lovetik",
        }


async def get_info_ytdlp(basic_info: dict) -> dict:
    """Gets advanced tiktok info from yt-dlp.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
    log.info("Advanced Info: YouTube-DLP.")
    # fallback source, since /photo/ URLs are not currently supported
    if info := await get_ytdlp_info(basic_info["original_link"]):
        log.debug("YouTube Advanced Info: %r.", info)
        return {
            "thumb": (
                None
                if len(info.get("thumbnails") or []) < 1
                else info["thumbnails"][0]["url"]
            ),
            "author_name": info["uploader"],
            "desc": info["description"],
            "advinfo_source": "yt-dlp",
        }


async def get_links_ytdlp(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from yt-dlp.

    Args:
        tiktok_info (dict): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    log.info("API: YouTube-DLP.")
    content = content_videos, content_images = [], []
    if not (info := await get_ytdlp_info(tiktok_info["original_link"])):
        return content
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
    for video in sorted(videos, key=lambda x: x["height"], reverse=True):
        cookies = {}
        if video_cookies := video.get("cookies"):
            log.info("Cookies found!")
            cookie = SimpleCookie()
            cookie.load(video_cookies)
            cookies = {key: morsel.value for key, morsel in cookie.items()}
        else:
            log.info("No cookies found!")
        extra = {"cookies": cookies, "headers": video["http_headers"]}
        if _ext := await get_content_extension(video["url"], **extra):
            log.info("Video extension: %s.", _ext)
            if _ext == "html":
                log.warning("Can't download video in html format.")
                continue
        _size = video.get("filesize") or video.get("filesize_approx") or 0
        if _size := await get_content_size(
            video["url"],
            headers=video.get("http_headers"),
            cookies=cookies,
        ):
            content_videos.append(
                TikTokVideo(
                    video["url"],
                    _size,
                    {"cookies": cookies, "headers": video.get("http_headers")},
                )
            )
    return content


async def get_links_tokcounter(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from TokCounter.

    Args:
        tiktok_info (dict): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    log.info("API: TokCounter.")
    content = content_videos, content_images = [], []
    # api info
    api = "https://tiktok.livecounts.io/video/download"
    # send request
    if response := await make_request.retry_with(stop=stop_after_attempt(1))(
        url=f"{api}/{tiktok_info['id']}",
        method="GET",
        headers={**FAKE_HEADERS, "Origin": "https://tokcounter.com"},
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return content
        log.debug("JSON: %r.", info)
        if not info["success"]:
            log.warning("Couldn't find tiktok video.")
            return content
        # process response
        log.debug("Getting links...")
        _link = info["video"]["downloadUrl"]
        if _ext := await get_content_extension(_link):
            log.info("Video extension: %s.", _ext)
            if _ext == "html":
                log.warning("Can't download video in html format.")
                return content
        else:
            log.info("Couldn't get video extension.")
        if _size := await get_content_size(_link):
            for _ in range(2):
                content_videos.append(TikTokVideo(_link, _size, {}))
        if not content_videos:
            log.warning("No content.")
    return content


async def get_links_tikmate_app(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from TikMate.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    log.info("API: TikMate App.")
    content = content_videos, content_images = [], []
    if info := await get_tikmate_app_info(tiktok_info["original_link"]):
        # process response
        log.debug("Getting links...")
        for _param in ("?hd=1", ""):
            _link = TIKMATE_LINK.format(info["token"], info["id"], _param)
            if _ext := await get_content_extension(_link):
                log.info("Video extension: %s.", _ext)
                if _ext == "html":
                    log.warning("Can't download video in html format.")
                    continue
            else:
                log.info("Couldn't get video extension.")
            if _size := await get_content_size(_link):
                content_videos.append(TikTokVideo(_link, _size, {}))
        if not content_videos:
            log.warning("No content.")
    return content


async def get_links_lovetik(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from LoveTik.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    log.info("API: LoveTik.")
    content = content_videos, content_images = [], []
    # api info
    base = "lovetik.com"
    api = f"https://{base}/api/ajax/search"
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded;" " charset=UTF-8",
            "Referer": f"https://{base}/",
        },
        data={"query": f"https://www.tiktok.com/@web/video/{tiktok_info['id']}"},
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return content
        log.debug("JSON: %r.", info)
        if info["status"] != "ok" or info["mess"].startswith("Error"):
            log.warning("Couldn't find tiktok video.")
            return content
        # process response
        log.debug("Getting links...")
        _link = info["links"][0]["a"]
        if _ext := await get_content_extension(_link):
            log.info("Video extension: %s.", _ext)
            if _ext == "html":
                log.warning("Can't download video in html format.")
                return content
        else:
            log.info("Couldn't get video extension.")
        if _size := await get_content_size(_link):
            for _ in range(2):
                content_videos.append(TikTokVideo(_link, _size, {}))
        if not content_videos:
            log.warning("No content.")
    return content


async def get_links_unduhtiktok(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from UnduhTiktok.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    log.info("API: UnduhTiktok.")
    content = content_videos, content_images = [], []
    # api info
    base = "unduhtiktok.com"
    api = f"https://{base}/wp-content/plugins/app-snaptik/api/tiktok.php"

    cookies = None
    if cookie := await make_request(
        "https://unduhtiktok.com/wp-content/plugins/app-snaptik//api/check.php",
        headers={
            **FAKE_HEADERS,
            "Referer": "https://unduhtiktok.com/",
            "DNT": "1",
            "Sec-GPC": "1",
            "Connection": "keep-alive",
            "Cookie": "pll_language=id",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Priority": "u=4",
        },
    ):
        if cookie.is_error or not (cookies := cookie.cookies):
            log.error("No token!")
            return content
    if phpsessid := cookies.get("PHPSESSID"):
        log.info("PHPSESSID: %s", phpsessid)
        cookies = {
            "PHPSESSID": phpsessid,
            "pll_language": "id",
        }
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": "application/json",
            "Origin": "https://unduhtiktok.com",
            "Connection": "keep-alive",
            "Referer": "https://unduhtiktok.com/",
        },
        cookies=cookies,
        proxy=True,
        json={
            "url": f"https://www.tiktok.com/@web/video/{tiktok_info['id']}",
        },
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return content
        log.debug("JSON: %r.", info)
        # video_id = info.get('aweme_id')
        # dynamic_cover = info.get('dynamic_cover')
        # desc = info.get('desc')
        # music = info.get('music')

        if not (images := info.get("imagePost", [])):
            log.warning("Couldn't find tiktok slides.")
        if not (previews := info.get("download_display_image", [])):
            log.warning("Couldn't find tiktok previews.")
            previews = list(images)
        if not (video := info.get("video")):
            log.warning("Couldn't find tiktok video.")
            return content
        # process response
        # process response
        log.debug("Getting links...")
        for image, preview in zip(images, previews):
            _prev = preview
            _link = image
            _size = await get_content_size(_link)
            _name = await get_content_name(_link, REGEX_TIKTOK_CDN)
            content_images.append(TikTokPhoto(_link, _size, _prev, _name))
        _link = video
        if _ext := await get_content_extension(_link, cookies=cookies):
            log.info("Video extension: %s.", _ext)
            if _ext == "html":
                log.warning("Can't download video in html format.")
                return content
        else:
            log.info("Couldn't get video extension.")
        if _size := await get_content_size(_link, cookies=cookies):
            for _ in range(2):
                content_videos.append(TikTokVideo(_link, _size, {"cookies": cookies}))
    return content


async def get_links_tikgo(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from TikGo.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    log.info("API: TikGo.")
    content = content_videos, content_images = [], []
    # api info
    base = "https://tikgo.me"
    api = f"{base}/api/"
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Referer": f"{base}/slide",
            "Content-Type": "application/json",
            "Origin": base,
            "Connection": "keep-alive",
        },
        json={
            "url": tiktok_info["fallback"],
        },
        follow_redirects=True,
        proxy=True,
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return content
        # if metadata := info.get("metadata"):
        #     title = metadata.get("title")
        #     author = metadata.get("author")
        #     thumb = metadata.get("thumbnail")
        #     duration = metadata.get("duration")
        if medias := info.get("medias"):
            for media in medias:
                if media.get("type") == "video":
                    if _ext := await get_content_extension(media["url"]):
                        log.info("Video extension: %s.", _ext)
                        if _ext == "html":
                            log.warning("Can't download video in html format.")
                            continue
                    else:
                        log.info("Couldn't get video extension.")
                    if _size := await get_content_size(media["url"]):
                        content_videos.append(TikTokVideo(media["url"], _size, {}))
                elif media.get("type") == "image":
                    _prev = media.get("url")
                    _link = media.get("url")
                    _size = await get_content_size(_link)
                    _name = await get_content_name(_link, REGEX_TIKTOK_CDN)
                    content_images.append(TikTokPhoto(_link, _size, _prev, _name))
    return content


async def get_slides_links_tikmate_io(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    log.info("API: TikMate Online.")
    content = content_videos, content_images = [], []
    # api info
    base = "https://tikmate.io"
    api = f"{base}/abc.php"
    # get token
    token = ""
    if response := await make_request(url=base, method="GET", proxy=True):
        # check response
        if response.is_error:
            log.warning("Request to the website failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        token_el = BeautifulSoup(response.content, "html.parser").find(
            "input", {"name": "token"}
        )
        if not token_el:
            log.warning("Obtaining token failed.")
            return content
        token = token_el["value"]
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": base,
            "Referer": f"{base}/",
            "Upgrade-Insecure-Requests": "1",
        },
        data={
            "url": tiktok_info["fallback"],
            "token": token,
        },
        follow_redirects=True,
        proxy=True,
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        log.debug("Request to API succeeded.")
        data = re.sub(r"<\/?[0-9a-zA-Z \-\=\.\"\'\/\\\|]+>", "", response.text)
        result = dehunter(data)
        if not result[0]:
            log.debug("Couldn't obtain HTML!")
            return content
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        log.debug("Obtained HTML: %s", html)
        # process response
        log.debug("Getting links...")
        soup = BeautifulSoup(html, "html.parser")
        videos = soup.find_all("a", class_="download-btn")
        photos = soup.find_all("div", class_="card")
        if videos and photos:
            for video in videos:
                if _size := await get_content_size(video["href"]):
                    content_videos.append(TikTokVideo(video["href"], _size, {}))
            for photo in photos:
                _prev = photo.img["src"]
                _link = photo.div.a["href"]
                _size = await get_content_size(_link)
                _name = await get_content_name(_link, REGEX_TIKMATE_IO)
                content_images.append(TikTokPhoto(_link, _size, _prev, _name))
    return content


async def get_slides_links_snaptik(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    log.info("API: SnapTik.")
    content = content_videos, content_images = [], []
    # api info
    base = "https://snaptik.app"
    api = f"{base}/abc2.php"
    # get token
    token = ""
    if response := await make_request(url=base, method="GET", proxy=True):
        # check response
        if response.is_error:
            log.warning("Request to the website failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        token_el = BeautifulSoup(response.content, "html.parser").find(
            "input", {"name": "token"}
        )
        if not token_el:
            log.warning("Obtaining token failed.")
            return content
        token = token_el["value"]
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": base,
            "Referer": f"{base}/",
        },
        data={
            "url": tiktok_info["fallback"],
            "token": token,
        },
        follow_redirects=True,
        proxy=True,
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        log.debug("Request to API succeeded.")
        data = re.sub(r"<\/?[0-9a-zA-Z \-\=\.\"\'\/\\\|]+>", "", response.text)
        result = dehunter(data)
        if not result[0]:
            log.debug("Couldn't obtain HTML!")
            return content
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        log.debug("Obtained HTML: %s", html)
        # process response
        log.debug("Getting links...")
        soup = BeautifulSoup(html, "html.parser")
        photos = soup.find_all("div", class_="photo")
        for photo in photos:
            _prev = photo.img["src"]
            _link = photo.div.a["href"]
            _size = await get_content_size(_link)
            _name = await get_content_name(_link, REGEX_SNAPTIK_APP)
            content_images.append(TikTokPhoto(_link, _size, _prev, _name))
    return content


async def get_links_downr(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from downr.org.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    log.info("API: downr.")
    content = content_videos, content_images = [], []
    # api info
    api = "https://downr.org/.netlify/functions/download"
    # send request
    if response := await make_request(
        api,
        method="POST",
        headers={
            **FAKE_HEADERS,
            "Referer": "https://downr.org/",
            "Content-Type": "application/json",
            "Origin": "https://downr.org",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Priority": "u=0",
        },
        json={"url": tiktok_info["fallback"]},
        follow_redirects=True,
        proxy=True,
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return content
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return content
        if info["error"]:
            log.warning("downr returned error: %r.", response.content)
            return content
        log.debug("downr info: %s.", info)
        if medias := info.get("medias"):
            for media in medias:
                if media.get("type") == "video":
                    if (_ext := media.get("extension", 0)) or (
                        _ext := await get_content_extension(media["url"])
                    ):
                        log.info("Video extension: %s.", _ext)
                        if _ext == "html":
                            log.warning("Can't download video in html format.")
                            continue
                    else:
                        log.info("Couldn't get video extension.")
                    if (_size := media.get("data_size", 0)) or (
                        _size := await get_content_size(media["url"])
                    ):
                        content_videos.append(TikTokVideo(media["url"], _size, {}))
                elif media.get("type") == "image":
                    _prev = media.get("url")
                    _link = media.get("url")
                    _size = await get_content_size(_link)
                    _name = await get_content_name(_link, REGEX_TIKTOK_CDN)
                    content_images.append(TikTokPhoto(_link, _size, _prev, _name))
    return content


async def get_tiktok_links(link: str) -> Optional[TikTokMedia]:
    """Gets tiktok links.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        Optional[TikTokMedia]: full tiktok info.
    """

    for get_basic_info in (
        get_basic_info_tiktok,  # original source
        get_basic_info_ytdlp,  # best source
        get_basic_info_tikmate,  # nice source
        get_basic_info_downr,  # nice source
        get_basic_info_url_expand,  # link source
    ):
        if basic_info := await get_basic_info(link):
            break
    else:
        return

    # add source link
    basic_info["original_link"] = link
    basic_info["source"] = TT["source"].format(**basic_info)
    basic_info["fallback"] = TT["fallback"].format(**basic_info)
    basic_info["kind"] = (
        TikTokMediaKind.SLIDESHOW
        if basic_info["type"] == "photo"
        else TikTokMediaKind.VIDEO
    )

    for get_info in (
        get_info_ytdlp,  # best
        get_info_tokcounter,  # good
        get_info_lovetik,  # okay
        get_tiktok_thumbnail,  # thumbnail
    ):
        if info := await get_info(basic_info):
            update_new(info, basic_info)
            if info.get("thumb"):
                break
    else:
        return

    basic_info["source"] = TT["source"].format(**basic_info)
    basic_info["fallback"] = TT["fallback"].format(**basic_info)
    basic_info["kind"] = (
        TikTokMediaKind.SLIDESHOW
        if basic_info["type"] == "photo"
        else TikTokMediaKind.VIDEO
    )

    log.info("TikTok info: %s.", info)

    if info["kind"] == TikTokMediaKind.VIDEO:
        log.info("TikTok type: video.")
        for get_links in (
            get_links_ytdlp,  # good
            get_links_tikmate_app,  # good
            get_links_tikgo,  # good
            get_links_tokcounter,  # good
            get_links_lovetik,  # good
            get_links_unduhtiktok,  # okay
            get_links_downr,  # nice
        ):
            if content := await get_links(info):
                content_videos, content_images = content
                if content_videos:
                    return TikTokMedia(**info, content=[*content_videos, *content_images])
            log.info("Trying another API...")
    else:
        log.info("TikTok type: slideshow.")
        content = content_videos, content_images = [], []
        for get_slides in (
            get_slides_links_tikmate_io,  # nice
            get_slides_links_snaptik,  # nice
            get_links_tikgo,  # good
            get_links_unduhtiktok,  # good
            get_links_downr,  # nice
        ):
            if content := await get_slides(info):
                content_videos, content_images = content
                if content_images:
                    return TikTokMedia(**info, content=[*content_videos, *content_images])
            log.info("Trying another API...")

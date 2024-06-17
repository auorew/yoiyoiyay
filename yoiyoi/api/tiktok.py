"""TikTok module"""
import asyncio
import json
import logging
import re

from http.cookies import SimpleCookie
from random import getrandbits
from typing import Optional, TypedDict

# parse json
import orjson

# yt-dlp
import yt_dlp

# async caching
from aiocache import cached

# beautiful soup
from bs4 import BeautifulSoup

# hardcore retrying
from tenacity import stop_after_attempt

# link types and other info
from ..api import LINKS, TikTokMediaKind

# TikTokVideo namedtuple
from ..api.namedtuples import TikTokMedia, TikTokPhoto, TikTokVideo

# fake headers and request helpers
from ..extra.request_helpers import (
    FAKE_HEADERS,
    get_file_name,
    get_file_size,
    make_request,
)

# deobfuscate js response
from .dehunter import dehunter

# url expanders
from .urlexpander import (
    expand_with_checkshorturl,
    expand_with_expandurl,
    expand_with_urlex,
)

# setup logger
log = logging.getLogger(__name__)

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
TikTok = TypedDict("TikTok", link=TikTokURL, size=TikTokSize)

# tikmate link
TIKMATE_LINK = "https://tikmate.app/download/{0}/{1}.mp4{2}"

# regex
REGEX_TIKMATE_ONLINE = re.compile(r"\.app_(?P<name>\w+)\.(?P<extension>\w{3,4})$")
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


async def get_url_info(link: str) -> dict:
    """Gets tiktok info from TikTok with URL expanders.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    for get_info in asyncio.as_completed(
        (
            expand_with_checkshorturl(link),  # good
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


async def get_tiktok_info(link: str) -> dict:
    """Gets tiktok info from TikTok.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    if (
        (response := await make_request(link, method="HEAD", proxy=True))
        and response.is_success
        and response.url.path != "/"
        and (info := re.search(TT["info"], response.url.path))
        and info["author"] != "web"
    ):
        log.debug("TikTok URL: %s.", response.url)
        return {**info.groupdict(), "info_source": "tiktok"}


async def get_ytdlp_basic_info(link: str) -> dict:
    """Gets basic tiktok info from yt-dlp.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    if info := await get_ytdlp_info(link):
        return {
            "id": info["id"],
            "author": info["uploader"],
            "type": "photo" if info["video_ext"] == "none" else "video",
            "info_source": "yt-dlp",
        }


async def get_tikmate_info(link: str) -> dict:
    """Gets tiktok info from TMATE.

    Args:
        link (str): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    if (info := await get_tikmate_app_info(link)) and info.get("success"):
        return {
            "id": info.get("id"),
            "author": info.get("author_id"),
            "author_name": info.get("author_name"),
            "type": "photo" if len(info.get("token", "")) > 100 else "video",
            "thumb": info.get("cover"),
            "desc": info.get("desc"),
            "info_source": "tikmate.app",
        }


async def get_tiktok_thumbnail(basic_info: dict) -> dict:
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
        return {
            "thumb": info["thumbnail_url"],
            "author_name": info["author_name"],
            "desc": info["title"],
            "advinfo_source": "tiktok_embed",
        }


async def get_tokcounter_info(basic_info: dict) -> dict:
    """Gets advanced tiktok info from TokCounter.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
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
        return {
            "thumb": None,  # info['video']['cover'] is animated
            "author_name": info["author"]["name"],
            "desc": info["video"]["title"],
            "advinfo_source": "tokcounter",
        }


async def get_lovetik_info(basic_info: dict) -> dict:
    """Gets advanced tiktok info from LoveTik.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
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
        return {
            "thumb": info["cover"],
            "author_name": info["author_name"],
            "desc": info["desc"],
            "advinfo_source": "lovetik",
        }


async def get_ytdlp_advanced_info(basic_info: dict) -> dict:
    """Gets advanced tiktok info from yt-dlp.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
    # fallback source, since /photo/ URLs are not currently supported
    if info := await get_ytdlp_info(basic_info["original_link"]):
        return {
            "thumb": info["thumbnails"][0]["url"],
            "author_name": info["uploader"],
            "desc": info["description"],
            "advinfo_source": "yt-dlp",
        }


async def get_ytdlp_links(tiktok_info: dict) -> list[Optional[TikTok]]:
    """Gets video links from yt-dlp.

    Args:
        tiktok_info (dict): tiktok info dictionary.

    Returns:
        list[TikTok]: tiktok video links and sizes.
    """
    content = []
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
        cookie = SimpleCookie()
        cookie.load(video["cookies"])
        cookies = {key: morsel.value for key, morsel in cookie.items()}
        content.append(
            TikTokVideo(
                video["url"],
                video["filesize"] or video["filesize_approx"] or 0,
                {"cookies": cookies, "headers": video["http_headers"]},
            )
        )
    return content


async def get_tokcounter_links(tiktok_info: dict) -> list[TikTok]:
    """Gets video links from TokCounter.

    Args:
        tiktok_info (dict): tiktok info dictionary.

    Returns:
        list[TikTok]: tiktok video links and sizes.
    """
    log.info("API: TokCounter.")
    content = []
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
        log.debug("Getting links...")
        _link = info["video"]["downloadUrl"]
        if _size := await get_file_size(_link):
            for _ in range(2):
                content.append(TikTokVideo(_link, _size, {}))
        if not content:
            log.warning("No content.")
    return content


async def get_tikmate_app_links(tiktok_info: dict) -> list[TikTok]:
    """Gets video links from TikMate.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        list[TikTok]: tiktok video links and sizes.
    """
    log.info("API: TikMate App.")
    content = []
    if info := await get_tikmate_app_info(tiktok_info["original_link"]):
        # process response
        log.debug("Getting links...")
        for _param in ("?hd=1", ""):
            _link = TIKMATE_LINK.format(info["token"], info["id"], _param)
            if _size := await get_file_size(_link):
                content.append(TikTokVideo(_link, _size, {}))
        if not content:
            log.warning("No content.")
    return content


async def get_lovetik_links(tiktok_info: dict) -> list[TikTok]:
    """Gets video links from LoveTik.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        list[TikTok]: tiktok video links and sizes.
    """
    log.info("API: LoveTik.")
    content = []
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
        # process response
        log.debug("Getting links...")
        _link = info["links"][0]["a"]
        if _size := await get_file_size(_link):
            for _ in range(2):
                content.append(TikTokVideo(_link, _size, {}))
        if not content:
            log.warning("No content.")
    return content


async def get_tikmate_io_media(
    tiktok_info: dict,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    log.info("API: TikMate Online.")
    content_videos, content_images = [], []
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
            return
        token_el = BeautifulSoup(response.content, "html.parser").find(
            "input", {"name": "token"}
        )
        if not token_el:
            log.warning("Obtaining token failed.")
            return
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
            return
        log.debug("Request to API succeeded.")
        data = re.sub(r"<\/?[0-9a-zA-Z \-\=\.\"\'\/\\\|]+>", "", response.text)
        result = dehunter(data)
        if not result[0]:
            log.debug("Couldn't obtain HTML!")
            return
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        log.debug("Obtained HTML: %s", html)
        # process response
        log.debug("Getting links...")
        soup = BeautifulSoup(html, "html.parser")
        videos = soup.find_all("a", class_="download-btn")
        photos = soup.find_all("div", class_="card")
        if videos and photos:
            for video in videos:
                if _size := await get_file_size(video["href"]):
                    content_videos.append(TikTokVideo(video["href"], _size, {}))
            for photo in photos:
                _prev = photo.img["src"]
                _link = photo.div.a["href"]
                _size = await get_file_size(_link)
                _name = await get_file_name(_link, REGEX_TIKMATE_ONLINE)
                content_images.append(TikTokPhoto(_link, _size, _prev, _name))
    return content_videos, content_images


async def get_cobalt_media(tiktok_info: dict) -> Optional[TikTokPhoto]:
    log.info("API: Cobalt.")
    content_images = []
    # api info
    base = "cobalt.tools"
    api = f"https://api.{base}/api/json"
    # send request
    if response := await make_request(
        url=api,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={"url": tiktok_info["source"]},
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
        if info["status"] != "picker":
            log.warning("Couldn't find tiktok photos.")
            return
        # process response
        log.debug("Getting links...")
        for photo in info["picker"]:
            _prev = photo["url"]
            _link = photo["url"]
            _size = await get_file_size(_link)
            _name = await get_file_name(_link, REGEX_COBALT_TOOLS)
            content_images.append(TikTokPhoto(_link, _size, _prev, _name))
        if not content_images:
            log.warning("No content.")
    return content_images


async def get_tiktok_links(link: str) -> Optional[TikTokMedia]:
    """Gets tiktok links.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        Optional[TikTokMedia]: full tiktok info.
    """

    for get_basic_info in asyncio.as_completed(
        (
            get_tiktok_info(link),  # original source
            get_url_info(link),  # link source
            get_ytdlp_basic_info(link),  # best source
            get_tikmate_info(link),  # nice source
        )
    ):
        if basic_info := await get_basic_info:
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

    for get_info in asyncio.as_completed(
        (
            get_ytdlp_advanced_info(basic_info),  # best
            get_tokcounter_info(basic_info),  # good
            get_lovetik_info(basic_info),  # okay
            get_tiktok_thumbnail(basic_info),  # thumbnail
        )
    ):
        if info := await get_info:
            update_new(info, basic_info)
            if info.get("thumb"):
                break
    else:
        return

    log.info("TikTok info: %s.", info)

    if info["kind"] == TikTokMediaKind.VIDEO:
        log.info("TikTok type: video.")
        for get_links in (
            get_ytdlp_links,  # good
            get_tikmate_app_links,  # good
            get_tokcounter_links,  # good
            get_lovetik_links,  # good
        ):
            if content := await get_links(info):
                return TikTokMedia(**info, content=content)
            log.info("Trying another API...")
    else:
        log.info("TikTok type: slideshow.")
        content_videos, content_images = [], []
        if content := await get_tikmate_io_media(info):
            content_videos, content_images = content[0], content[1]
        if not content_images:
            content_images = await get_cobalt_media(info)
        return TikTokMedia(**info, content=[*content_videos, *content_images])

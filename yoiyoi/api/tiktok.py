"""TikTok module"""
import asyncio
import logging
import re

from typing import Optional, TypedDict

# parse json
import orjson

# yt-dlp
import yt_dlp

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

# regex
REGEX_TIKMATE_ONLINE = re.compile(r"\.app_(?P<name>\w+)\.(?P<extension>\w{3,4})$")


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
            and "@web" not in url
            and (info := re.search(TT["info"], url))
        ):
            return {**info.groupdict(), "info_source": "urlexpander"}
    else:
        return


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
    ):
        log.debug("TikTok URL: %s.", response.url)
        return {**info.groupdict(), "info_source": "tiktok"}


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
            "kind": TikTokMediaKind.SLIDESHOW
            if info["video"]["downloadUrl"].endswith("mp3")
            else TikTokMediaKind.VIDEO,
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
        data={"query": TT["source"].format(**basic_info)},
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
        return {
            "thumb": info["cover"],
            "kind": TikTokMediaKind.SLIDESHOW
            if len(info["links"]) == 1
            else TikTokMediaKind.VIDEO,
            "author_name": info["author_name"],
            "desc": info["desc"],
            "advinfo_source": "lovetik",
        }


async def get_ytdlp_info(basic_info: dict) -> dict:
    """Gets advanced tiktok info from yt-dlp.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
    with yt_dlp.YoutubeDL(ytdlp_ops) as ytdl:
        try:
            info = ytdl.extract_info(basic_info["source"])
        except yt_dlp.utils.DownloadError:
            log.warning("yt-dlp: Unable to download.")
            return
        return {
            "thumb": info["thumbnails"][0]["url"],
            "kind": TikTokMediaKind.SLIDESHOW
            if info["video_ext"] == "none"
            else TikTokMediaKind.VIDEO,
            "author_name": info["creator"],
            "desc": info["description"],
            "advinfo_source": "yt-dlp",
        }


async def get_ytdlp_links(tiktok_info: dict) -> list[Optional[TikTok]]:
    """Gets video links from yt-dlp.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        list[TikTok]: tiktok video links and sizes.
    """
    content = []
    with yt_dlp.YoutubeDL(ytdlp_ops) as ytdl:
        info = ytdl.extract_info(tiktok_info["source"])
        videos = []
        for video_format in info["formats"]:
            if (
                video_format["height"]
                and video_format["vcodec"] != "none"
                and video_format["acodec"] != "none"
            ):
                videos.append(video_format)
        for video in sorted(videos, key=lambda x: x["height"], reverse=True):
            content.append(
                TikTokVideo(
                    video["url"],
                    video["filesize"] or video["filesize_approx"] or 0,
                )
            )
    return content


async def get_tokcounter_links(tiktok_info: dict) -> list[TikTok]:
    """Gets video links from TokCounter.

    Args:
        tiktok_info (str): tiktok info dictionary.

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
                content.append(TikTokVideo(_link, _size))
        if not content:
            log.warning("No content.")
    return content


async def get_tikmate_online_info(tiktok_info: dict) -> list[TikTok]:
    log.info("API: TikMate Online.")
    content = []
    # api info
    base = "https://tikmate.online"
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
            "url": tiktok_info["source"],
            "token": token,
        },
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
                    content.append(TikTokVideo(video["href"], _size))
            for photo in photos:
                _prev = photo.img["src"]
                _link = photo.div.a["href"]
                _size = await get_file_size(_link)
                _name = await get_file_name(_link, REGEX_TIKMATE_ONLINE)
                content.append(TikTokPhoto(_link, _size, _prev, _name))
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
    # api info
    base = "tikmate.app"
    api = f"https://api.{base}/api/lookup"
    tikmate = "https://tikmate.app/download/{0}/{1}.mp4{2}"
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded;" " charset=UTF-8",
            "Referer": f"https://{base}/",
        },
        data={"url": tiktok_info["source"]},
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
        # process response
        log.debug("Getting links...")
        for _param in ("?hd=1", ""):
            _link = tikmate.format(info["token"], info["id"], _param)
            if _size := await get_file_size(_link):
                content.append(TikTokVideo(_link, _size))
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
            for i in range(2):
                content.append(TikTokVideo(_link, _size))
        if not content:
            log.warning("No content.")
    return content


async def get_tiktok_links(link: str) -> Optional[TikTokMedia]:
    """Gets tiktok links.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        Optional[TikTokMedia]: full tiktok info.
    """

    for get_basic_info in asyncio.as_completed(
        (
            get_tiktok_info(link),  # source
            get_url_info(link),  # source
        )
    ):
        if basic_info := await get_basic_info:
            break
    else:
        return

    # add source link
    basic_info["source"] = TT["source"].format(**basic_info)

    for get_info in asyncio.as_completed(
        (
            get_ytdlp_info(basic_info),  # best
            get_tokcounter_info(basic_info),  # good
            get_lovetik_info(basic_info),  # okay
        )
    ):
        if info := await get_info:
            info.update(basic_info)
            if info["thumb"]:
                break
    else:
        return

    log.info("TikTok info: %s.", info)

    if info["kind"] == TikTokMediaKind.VIDEO:
        log.info("TikTok type: video.")
        for get_links in (
            get_tikmate_app_links,  # good
            get_tokcounter_links,  # good
            get_lovetik_links,  # good
            get_ytdlp_links,  # good
        ):
            if content := await get_links(info):
                return TikTokMedia(**info, content=content)
            log.info("Trying another API...")
    else:
        log.info("TikTok type: slideshow.")
        if content := await get_tikmate_online_info(info):
            return TikTokMedia(**info, content=content)

"""TikTok API"""

import asyncio
import re
import secrets

from http.cookies import SimpleCookie
from typing import Optional, TypedDict
from urllib.parse import quote

# parse json
import msgspec

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

# proxy
from yoiyoi.app.proxy import proxy_manager

# retry proxy max tries
from yoiyoi.extra import RETRY_PROXY_MAX_TRIES

# request helpers
from yoiyoi.extra.request_helpers import get_fake_headers, get_request_info

# retriers
from yoiyoi.extra.request_retriers import retry_request

# requests
from yoiyoi.extra.requests import (
    get_content_extension,
    get_content_name,
    get_content_size,
    make_request,
)

# base opts
from yoiyoi.services.base import ytdlp_opts_base

# link types and other info
from yoiyoi.services.constants import LINKS, TikTokMediaKind

# deobfuscate js response
from yoiyoi.services.dehunter import dehunter

# TikTokVideo namedtuple
from yoiyoi.services.namedtuples import TikTokMedia, TikTokPhoto, TikTokVideo

# setup logger
log = structlog.get_logger(__name__, service="tiktok")

# tiktok thumbnail link
TT = LINKS["tiktok"]

# yt-dlp options
ytdlp_ops = {
    **ytdlp_opts_base,
    "verbose": True,
    "simulate": True,
    "forcejson": True,
}

# tiktok info typing
TikTokURL = str
TikTokSize = int


class AdvancedInfo(TypedDict, total=False):
    author_name: str
    desc: str
    thumb: str
    advinfo_source: str


class TikTokInfo(AdvancedInfo, total=False):
    id: int
    author: str
    author_name: str
    type: str
    desc: str
    thumb: str
    original_link: str
    source: str
    fallback: str
    kind: int
    info_source: str
    advinfo_source: str


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
    keys_to_del = [k for k, v in old_dict.items() if v is None]
    for k in keys_to_del:
        del old_dict[k]
    for key, value in new_dict.items():
        if key not in old_dict and value is not None:
            old_dict[key] = value


def enrich_tiktok_info(info: TikTokInfo, link: str) -> TikTokInfo:
    info["original_link"] = link
    if info.get("author") and info.get("id"):
        info["fallback"] = TT["fallback"].format(**info)
        if info.get("type"):
            info["source"] = TT["source"].format(**info)
    if info.get("type"):
        info["kind"] = (
            TikTokMediaKind.SLIDESHOW
            if info["type"] == "photo"
            else TikTokMediaKind.VIDEO
        )
    return info


async def fetch_api_json(
    url: str,
    method: str = "POST",
    api_log: structlog.BoundLogger = log,
    retry_with: dict = None,
    **kwargs,
) -> dict:
    if not retry_with:
        response = await make_request(url=url, method=method, **kwargs)
    else:
        response = await make_request.retry_with(**retry_with)(
            url=url, method=method, **kwargs
        )
    if response is None:
        api_log.error(
            "No response object!",
            request={
                "method": method,
                "url": url,
                "headers": kwargs.get("headers", {}),
                "body": kwargs.get("data", None) or kwargs.get("json", None),
            },
        )
        return {}
    request_info = await get_request_info(response)
    if response.is_error:
        api_log.warning(
            "Request to API failed: %s.",
            response,
            status_code=response.status_code,
            response=response.content,
            request=request_info,
        )
        return {}
    try:
        info = msgspec.json.decode(response.content)
        api_log.debug("Loaded JSON.", json=info, request=request_info)
        return info
    except msgspec.DecodeError:
        api_log.warning(
            "Couldn't decode json response.",
            response=response.content,
            request=request_info,
        )
        return {}


def build_multipart_form(fields: dict, boundary: str) -> str:
    payload_parts = []
    for name, value in fields.items():
        payload_parts.extend(
            [
                f"--{boundary}",
                f'Content-Disposition: form-data; name="{name}"',
                "",
                str(value),
            ]
        )
    payload_parts.append(f"--{boundary}--")
    payload_parts.append("")  # Final newline
    return "\r\n".join(payload_parts)


@cached(
    ttl=15,
    key_builder=lambda fn, *a, **kw: a[0],
    skip_cache_func=lambda r: r is None,
)
@retry_request
async def get_ytdlp_info(link: str) -> Optional[AdvancedInfo]:
    """Gets tiktok info from yt-dlp.

    Args:
        link (str): formatted tiktok link.

    Returns:
        Optional[dict]: tiktok info.
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


@cached(
    ttl=15,
    key_builder=lambda fn, *a, **kw: a[0],
    skip_cache_func=lambda r: r is None,
)
async def get_tikmate_app_info(link: str) -> Optional[dict]:
    """Gets tiktok info from TikMate.App.

    Args:
        link (str): formatted tiktok link.

    Returns:
        Optional[dict]: tiktok id and author info.
    """
    api_log = log.bind(api="tikmate", type="info")
    # api info
    base = "tikmate.app"
    api = f"https://api.{base}/api/lookup"
    # send request
    boundary = f"----geckoformboundary{secrets.token_hex(16)}"
    api_log.debug("Boundary: %r.", boundary)
    if info := await fetch_api_json(
        url=api,
        api_log=api_log,
        headers={
            **get_fake_headers(),
            "Accept": "*/*",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": f"https://{base}",
            "DNT": "1",
            "Sec-GPC": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Priority": "u=0",
        },
        data=build_multipart_form({"url": link}, boundary),
        with_proxy=True,
    ):
        # process response
        if not info.get("success", False):
            api_log.warning("Couldn't find tiktok video.")
            return
        return info


@cached(
    ttl=300,  # Cache session cookie for 5 minutes
    key_builder=lambda fn, *a, **kw: "downr_session_cookie",
    skip_cache_func=lambda r: not r,
)
async def get_downr_session_cookies() -> dict:
    """Hits downr's analytics endpoint to acquire the required session token."""
    api_log = log.bind(api="downr", type="session")
    if response := await make_request(
        url="https://downr.org/.netlify/functions/analytics",
        method="GET",
        headers={
            **get_fake_headers(),
            "Accept": "*/*",
            "Referer": "https://downr.org/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Priority": "u=4",
        },
        with_proxy=True,
    ):
        if response.cookies:
            api_log.debug(
                "Acquired session cookies via analytics.",
                cookies=dict(response.cookies),
            )
            return dict(response.cookies)
    return {}


@cached(
    ttl=15,
    key_builder=lambda fn, *a, **kw: a[0],
    skip_cache_func=lambda r: r is None,
)
async def get_downr_info(link: str) -> Optional[dict]:
    """Gets raw TikTok payload from downr.org.

    Args:
        link (str): TikTok URL link.

    Returns:
        Optional[dict]: Raw API response JSON.
    """
    api_log = log.bind(api="downr", type="raw")

    # Fetch dynamic session cookie before making API call
    cookies = await get_downr_session_cookies()

    if info := await fetch_api_json(
        url="https://downr.org/.netlify/functions/bbc",
        method="POST",
        api_log=api_log,
        headers={
            **get_fake_headers(),
            "Referer": "https://downr.org/",
            "Content-Type": "application/json",
            "Origin": "https://downr.org",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Priority": "u=0",
        },
        cookies=cookies,
        json={"url": link},
        follow_redirects=True,
        with_proxy=True,
    ):
        return info
    return None


@cached(
    ttl=15,
    key_builder=lambda fn, *a, **kw: a[0],
    skip_cache_func=lambda r: r is None,
)
async def get_premierely_info(link: str) -> Optional[dict]:
    """Gets raw TikTok payload from premierely.io.

    Args:
        link (str): TikTok URL link.

    Returns:
        Optional[dict]: Raw API response JSON.
    """
    api_log = log.bind(api="premierely", type="raw")
    base = "premierely.io"
    encoded_url = quote(link, safe="")
    api = (
        f"https://{base}/tools/tiktok-to-mp3/tiktok-api.php?action=info&url={encoded_url}"
    )

    if info := await fetch_api_json(
        url=api,
        method="GET",
        api_log=api_log,
        headers={
            **get_fake_headers(),
            "Accept": "*/*",
            "Referer": f"https://{base}/tools/tiktok-video-downloader/",
        },
        retry_with=dict(stop=stop_after_attempt(2)),
        with_proxy=True,
    ):
        return info
    return None


async def get_basic_info_tiktok(link: str | dict) -> Optional[TikTokInfo]:
    """Gets tiktok info from TikTok.

    Args:
        link (str | dict): formatted tiktok link.

    Returns:
        Optional[TikTokInfo]: tiktok id and author info.
    """
    """Gets tiktok info from TikTok."""
    api_log = log.bind(api="tiktok", type="info")
    target_url = (
        link
        if isinstance(link, str)
        else link.get("original_link") or link.get("fallback")
    )
    if not target_url:
        return None

    if (
        (response := await make_request(target_url, method="HEAD", with_proxy=True))
        and response.is_success
        and response.url.path != "/"
        and (info := re.search(TT["info"], response.url.path))
        and info["author"] != "web"
    ):
        api_log.debug("TikTok URL: %s.", response.url)
        return TikTokInfo(
            **info.groupdict(),
            info_source="tiktok",
        )


async def get_basic_info_ytdlp(link: str | dict) -> Optional[TikTokInfo]:
    """Gets basic tiktok info from yt-dlp.

    Args:
        link (str | dict): formatted tiktok link.

    Returns:
        Optional[TikTokInfo]: tiktok id and author info.
    """
    api_log = log.bind(api="yt-dlp", type="info")
    target_url = (
        link
        if isinstance(link, str)
        else link.get("original_link") or link.get("fallback")
    )
    if not target_url:
        return None

    if info := await get_ytdlp_info(target_url):
        api_log.debug("Loaded JSON.", json=info)
        return TikTokInfo(
            id=int(info["id"], 0),
            author=info["uploader"],
            author_name=info.get("uploader"),
            desc=info.get("description"),
            thumb=(
                None
                if len(info.get("thumbnails") or []) < 1
                else info["thumbnails"][0]["url"]
            ),
            type=(
                "photo"
                if info.get("ext", "") == "none" or info.get("video_ext", "") == "none"
                else "video"
            ),
            info_source="yt-dlp",
        )


async def get_basic_info_downr(link: str | dict) -> Optional[TikTokInfo]:
    """Gets basic tiktok info from downr.org.

    Args:
        link (str | dict): formatted tiktok link.

    Returns:
        Optional[TikTokInfo]: tiktok id and author info.
    """
    api_log = log.bind(api="downr", type="info")
    target_url = (
        link
        if isinstance(link, str)
        else link.get("original_link") or link.get("fallback")
    )
    if not target_url:
        return None

    if info := await get_downr_info(target_url):
        if info.get("error"):
            api_log.warning("downr returned an error.", json=info)
            return None

        tiktok_type = "video"
        if medias := info.get("medias"):
            for media in medias:
                if media.get("type") == "video":
                    tiktok_type = "video"
                    break
                elif media.get("type") == "image":
                    tiktok_type = "photo"
                    break

        return TikTokInfo(
            id=int(info.get("id", 0)),
            author=info.get("unique_id"),
            author_name=info.get("author"),
            type=tiktok_type,
            desc=info.get("title"),
            thumb=info.get("thumbnail"),
            info_source="downr",
        )


async def get_basic_info_tikmate(link: str | dict) -> Optional[TikTokInfo]:
    """Gets tiktok info from TikMate.

    Args:
        link (str | dict): formatted tiktok link.

    Returns:
        dict: tiktok id and author info.
    """
    target_url = (
        link
        if isinstance(link, str)
        else link.get("original_link") or link.get("fallback")
    )
    if not target_url:
        return None

    if info := await get_tikmate_app_info(target_url):
        return TikTokInfo(
            id=int(info.get("id", 0)),
            author=info.get("author_id"),
            author_name=info.get("author_name"),
            type=(
                "photo"
                if "photomode" in info.get("cover", "")
                or "photomode" in info.get("dynamic_cover", "")
                else "video"
            ),
            thumb=info.get("cover"),
            desc=info.get("desc"),
            info_source="tikmate.app",
        )


async def get_info_tokcounter(basic_info: dict) -> Optional[AdvancedInfo]:
    """Gets advanced tiktok info from TokCounter.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        Optional[AdvancedInfo]: advanced tiktok info.
    """
    api_log = log.bind(api="tokcounter", type="advinfo")
    # api info
    api = "https://tiktok-api.tokcounter.com/video/data"

    # send request
    if info := await fetch_api_json(
        url=f"{api}/{basic_info['id']}",
        method="GET",
        headers={
            **get_fake_headers(),
            "Origin": "https://tokcounter.com",
            "Referer": "https://tokcounter.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        },
        retry_with=dict(stop=stop_after_attempt(2)),
        with_proxy=True,
    ):
        # process response
        if not info.get("success"):
            api_log.warning("Couldn't find tiktok video.")
            return None

        author_info = info.get("author", {})

        return AdvancedInfo(
            thumb=None,  # too small
            author_name=author_info.get("username"),
            desc=info.get("title"),
            advinfo_source="tokcounter",
        )


async def get_info_ytdlp(basic_info: dict) -> Optional[AdvancedInfo]:
    """Gets advanced tiktok info from yt-dlp.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        dict: advanced tiktok info.
    """
    api_log = log.bind(api="yt-dlp", type="advinfo")
    # fallback source, since /photo/ URLs are not currently supported
    if info := await get_ytdlp_info(basic_info["fallback"]):
        api_log.debug("Loaded JSON.", json=info)
        # process response
        return AdvancedInfo(
            thumb=(
                None
                if len(info.get("thumbnails") or []) < 1
                else info["thumbnails"][0]["url"]
            ),
            author_name=info["uploader"],
            desc=info["description"],
            advinfo_source="yt-dlp",
        )


async def get_info_premierely(basic_info: dict) -> Optional[AdvancedInfo]:
    """Gets advanced tiktok info from Premierely.

    Args:
        basic_info (dict): basic tiktok info.

    Returns:
        Optional[AdvancedInfo]: advanced tiktok info.
    """
    api_log = log.bind(api="premierely", type="advinfo")
    target_url = basic_info.get("original_link") or basic_info["fallback"]

    if info := await get_premierely_info(target_url):
        if not info.get("ok"):
            api_log.warning("Couldn't find TikTok media from Premierely.")
            return None

        return AdvancedInfo(
            thumb=info.get("thumbnail"),
            author_name=info.get("authorName") or info.get("author"),
            desc=info.get("title"),
            advinfo_source="premierely",
        )


async def get_links_ytdlp(
    tiktok_info: TikTokInfo,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from yt-dlp.

    Args:
        tiktok_info (dict): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    api_log = log.bind(api="yt-dlp", type="links")
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
            api_log.info("Cookies found!")
            cookie = SimpleCookie()
            cookie.load(video_cookies)
            cookies = {key: morsel.value for key, morsel in cookie.items()}
        else:
            api_log.info("No cookies found!")
        extra = {"cookies": cookies, "headers": video["http_headers"]}
        if _ext := await get_content_extension(video["url"], **extra):
            api_log.info("Video extension: %s.", _ext)
            if _ext == "html":
                api_log.warning("Can't download video in html format.")
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


async def get_links_tikmate_app(
    tiktok_info: TikTokInfo,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from TikMate.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    api_log = log.bind(api="tikmate", type="links")
    content = content_videos, content_images = [], []
    if info := await get_tikmate_app_info(tiktok_info["original_link"]):
        # process response
        api_log.debug("Getting links...")
        for _param in ("?hd=1", ""):
            _link = TIKMATE_LINK.format(info["token"], info["id"], _param)
            if _ext := await get_content_extension(_link):
                api_log.info("Video extension: %s.", _ext)
                if _ext == "html":
                    api_log.warning("Can't download video in html format.")
                    continue
            else:
                api_log.info("Couldn't get video extension.")
            if _size := await get_content_size(_link):
                content_videos.append(TikTokVideo(_link, _size, {}))
        if not content_videos:
            api_log.warning("No content.")
    return content


async def get_links_unduhtiktok(
    tiktok_info: TikTokInfo,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from UnduhTiktok.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    api_log = log.bind(api="unduhtiktok", type="links")
    content = content_videos, content_images = [], []
    # api info
    base = "unduhtiktok.com"
    api = f"https://{base}/wp-content/plugins/app-snaptik/api/tiktok.php"
    # get cookies
    cookies = None
    if cookie := await make_request(
        "https://unduhtiktok.com/wp-content/plugins/app-snaptik//api/check.php",
        headers={
            **get_fake_headers(),
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
            api_log.error("No token!")
            return content
    if phpsessid := cookies.get("PHPSESSID"):
        api_log.info("PHPSESSID: %s", phpsessid)
        cookies = {
            "PHPSESSID": phpsessid,
            "pll_language": "id",
        }
    # send request
    if info := await fetch_api_json(
        url=api,
        headers={
            **get_fake_headers(),
            "Content-Type": "application/json",
            "Origin": "https://unduhtiktok.com",
            "Connection": "keep-alive",
            "Referer": "https://unduhtiktok.com/",
        },
        cookies=cookies,
        with_proxy=True,
        json={
            "url": f"https://www.tiktok.com/@web/video/{tiktok_info['id']}",
        },
    ):
        # process response
        if not (images := info.get("imagePost", [])):
            api_log.warning("Couldn't find tiktok slides.")
        if not (previews := info.get("download_display_image", [])):
            api_log.warning("Couldn't find tiktok previews.")
            previews = list(images)
        if not (video := info.get("video")):
            api_log.warning("Couldn't find tiktok video.")
            return content
        # video_id = info.get('aweme_id')
        # dynamic_cover = info.get('dynamic_cover')
        # desc = info.get('desc')
        # music = info.get('music')

        api_log.debug("Getting links...")
        for image, preview in zip(images, previews):
            _prev = preview
            _link = image
            _name = await get_content_name(_link, REGEX_TIKTOK_CDN)
            if _size := await get_content_size(_link):
                content_images.append(TikTokPhoto(_link, _size, _prev, _name))
            else:
                api_log.error("Failed to download.")
                content_images = []
                return content
        _link = video
        if _ext := await get_content_extension(_link, cookies=cookies):
            api_log.info("Video extension: %s.", _ext)
            if _ext == "html":
                api_log.warning("Can't download video in html format.")
                return content
        else:
            api_log.info("Couldn't get video extension.")
        if _size := await get_content_size(_link, cookies=cookies):
            for _ in range(2):
                content_videos.append(TikTokVideo(_link, _size, {"cookies": cookies}))
    return content


async def get_slides_links_tikmate_io(
    tiktok_info: TikTokInfo,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    api_log = log.bind(api="tikmate.io", type="links")
    content = content_videos, content_images = [], []
    # api info
    base = "https://tikmate.io"
    api = f"{base}/abc.php"
    # get token
    token = ""
    if response := await make_request(url=base, method="GET", with_proxy=True):
        # check response
        if response.is_error:
            api_log.warning("Request to the website failed: %s.", response)
            api_log.debug("Response: %s", response.content)
            return content
        token_el = BeautifulSoup(response.content, "html.parser").find(
            "input", {"name": "token"}
        )
        if not token_el:
            api_log.warning("Obtaining token failed.")
            return content
        token = token_el["value"]
    # send request
    if response := await make_request(
        url=api,
        headers={
            **get_fake_headers(),
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
        with_proxy=True,
    ):
        # check response
        if response.is_error:
            api_log.warning("Request to API failed: %s.", response)
            api_log.debug("Response: %s", response.content)
            return content
        api_log.debug("Request to API succeeded.")
        data = re.sub(r"<\/?[0-9a-zA-Z \-\=\.\"\'\/\\\|]+>", "", response.text)
        result = dehunter(data)
        if not result[0]:
            api_log.debug("Couldn't obtain HTML!")
            return content
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        api_log.debug("Obtained HTML: %s", html)
        # process response
        api_log.debug("Getting links...")
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
                _name = await get_content_name(_link, REGEX_TIKMATE_IO)
                if _size := await get_content_size(_link):
                    content_images.append(TikTokPhoto(_link, _size, _prev, _name))
                else:
                    api_log.error("Failed to download.")
                    content_images = []
                    return content
    return content


async def get_slides_links_snaptik(
    tiktok_info: TikTokInfo,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    api_log = log.bind(api="snaptik", type="links")
    content = content_videos, content_images = [], []
    # api info
    base = "https://snaptik.app"
    api = f"{base}/abc2.php"
    # get token
    token = ""
    if response := await make_request(url=base, method="GET", with_proxy=True):
        # check response
        if response.is_error:
            api_log.warning("Request to the website failed: %s.", response)
            api_log.debug("Response: %s", response.content)
            return content
        token_el = BeautifulSoup(response.content, "html.parser").find(
            "input", {"name": "token"}
        )
        if not token_el:
            api_log.warning("Obtaining token failed.")
            return content
        token = token_el["value"]
    # send request
    if response := await make_request(
        url=api,
        headers={
            **get_fake_headers(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": base,
            "Referer": f"{base}/",
        },
        data={
            "url": tiktok_info["fallback"],
            "token": token,
        },
        follow_redirects=True,
        with_proxy=True,
    ):
        # process response
        if response.is_error:
            api_log.warning("Request to API failed: %s.", response)
            api_log.debug("Response: %s", response.content)
            return content
        api_log.debug("Request to API succeeded.")
        data = re.sub(r"<\/?[0-9a-zA-Z \-\=\.\"\'\/\\\|]+>", "", response.text)
        result = dehunter(data)
        if not result[0]:
            api_log.debug("Couldn't obtain HTML!")
            return content
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        api_log.debug("Obtained HTML: %s", html)
        api_log.debug("Getting links...")
        soup = BeautifulSoup(html, "html.parser")
        photos = soup.find_all("div", class_="photo")
        for photo in photos:
            _prev = photo.img["src"]
            _link = photo.div.a["href"]
            _name = await get_content_name(_link, REGEX_SNAPTIK_APP)
            if _size := await get_content_size(_link):
                content_images.append(TikTokPhoto(_link, _size, _prev, _name))
            else:
                api_log.error("Failed to download.")
                content_images = []
                return content
    return content


async def get_links_downr(
    tiktok_info: TikTokInfo,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video links from downr.org.

    Args:
        tiktok_info (TikTokInfo): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video links and sizes.
    """
    api_log = log.bind(api="downr", type="links")
    content = content_videos, content_images = [], []
    link = tiktok_info.get("original_link") or tiktok_info["fallback"]

    if info := await get_downr_info(link):
        if info.get("error"):
            api_log.warning("downr returned error.", json=info)
            return content
        api_log.debug("Loaded JSON.", json=info)
        if medias := info.get("medias"):
            for media in medias:
                if media.get("type") == "video":
                    if (_ext := media.get("extension", 0)) or (
                        _ext := await get_content_extension(media["url"])
                    ):
                        api_log.info("Video extension: %s.", _ext)
                        if _ext == "html":
                            api_log.warning("Can't download video in html format.")
                            continue
                    else:
                        api_log.info("Couldn't get video extension.")
                    if (_size := media.get("data_size", 0)) or (
                        _size := await get_content_size(media["url"])
                    ):
                        content_videos.append(TikTokVideo(media["url"], _size, {}))
                elif media.get("type") == "image":
                    _prev = media.get("url")
                    _link = media.get("url")
                    _name = await get_content_name(_link, REGEX_TIKTOK_CDN)
                    if _size := await get_content_size(_link):
                        content_images.append(TikTokPhoto(_link, _size, _prev, _name))
                    else:
                        api_log.error("Failed to download.")
                        content_images = []
                        return content
    return content


async def get_links_premierely(
    tiktok_info: TikTokInfo,
) -> tuple[list[TikTokVideo], list[TikTokPhoto]]:
    """Gets video and photo links from Premierely.

    Args:
        tiktok_info (TikTokInfo): tiktok info dictionary.

    Returns:
        tuple[list[TikTokVideo], list[TikTokPhoto]]: tiktok video and photo links.
    """
    api_log = log.bind(api="premierely", type="links")
    content = content_videos, content_images = [], []
    link = tiktok_info.get("original_link") or tiktok_info["fallback"]

    if info := await get_premierely_info(link):
        if not info.get("ok"):
            api_log.warning("Premierely returned an error or no media.", json=info)
            return content

        api_log.debug("Loaded JSON.", json=info)

        # Process slideshow images
        if images := info.get("images"):
            for img_url in images:
                _prev = img_url
                _link = img_url
                _name = await get_content_name(_link, REGEX_TIKTOK_CDN)
                if _size := await get_content_size(_link):
                    content_images.append(TikTokPhoto(_link, _size, _prev, _name))
                else:
                    api_log.error("Failed to download image.")
                    content_images = []
                    return content

        # Process video links if not a photo slideshow
        if not content_images:
            video_urls = []
            audio_url = info.get("audioUrl")
            for key in ("hdVideoUrl", "videoUrl"):
                if (
                    (v_url := info.get(key))
                    and v_url not in video_urls
                    and v_url != audio_url
                ):
                    video_urls.append(v_url)

            for _link in video_urls:
                if _ext := await get_content_extension(_link):
                    api_log.info("Video extension: %s.", _ext)
                    if _ext in ("html", "mp3"):
                        api_log.warning("Invalid video extension: %s.", _ext)
                        continue
                else:
                    api_log.info("Couldn't get video extension.")

                if _size := await get_content_size(_link):
                    content_videos.append(TikTokVideo(_link, _size, {}))

    return content


BASIC_INFO_PROVIDERS = (
    get_basic_info_tiktok,  # original
    get_basic_info_ytdlp,  # best
    get_basic_info_tikmate,  # nice
    get_basic_info_downr,  # nice
)

ADVANCED_INFO_PROVIDERS = (
    get_info_ytdlp,  # best
    get_info_tokcounter,  # good
    get_info_premierely,  # okay
    get_basic_info_downr,  # fallback metadata
    get_basic_info_tikmate,  # fallback metadata
)

VIDEO_PROVIDERS = (
    get_links_tikmate_app,  # good
    get_links_ytdlp,  # good
    get_links_premierely,  # ???
    get_links_unduhtiktok,  # okay
    get_links_downr,  # nice
)

SLIDE_PROVIDERS = (
    get_slides_links_tikmate_io,  # nice
    get_slides_links_snaptik,  # nice
    get_links_premierely,  # ???
    get_links_unduhtiktok,  # good
    get_links_downr,  # nice
)


async def get_tiktok_links(link: str) -> Optional[TikTokMedia]:
    """Gets tiktok links.

    Args:
        tiktok_info (str): tiktok info dictionary.

    Returns:
        Optional[TikTokMedia]: full tiktok info.
    """

    for get_basic_info in BASIC_INFO_PROVIDERS:
        if basic_info := await get_basic_info(link):
            break
    else:
        return

    # add source link
    info = enrich_tiktok_info(basic_info, link)

    for get_info in ADVANCED_INFO_PROVIDERS:
        if all(info.get(k) for k in ("author_name", "desc", "thumb")):
            break
        if adv_info := await get_info(info):
            if "advinfo_source" not in adv_info and "info_source" in adv_info:
                adv_info["advinfo_source"] = adv_info["info_source"]
            update_new(info, adv_info)
            if info.get("type") and "kind" not in info:
                enrich_tiktok_info(info, link)
    else:
        if not all(info.get(k) for k in ("author_name", "desc", "thumb")):
            return

    # Ensure advinfo_source always has a value
    info.setdefault("advinfo_source", info.get("info_source", "unknown"))

    log.info("TikTok info: %s.", info)

    if info["kind"] == TikTokMediaKind.VIDEO:
        log.info("TikTok type: video.")
        for get_links in VIDEO_PROVIDERS:
            if content := await get_links(info):
                content_videos, content_images = content
                if content_videos:
                    return TikTokMedia(**info, content=[*content_videos, *content_images])
            log.info("Trying another API...")
    else:
        log.info("TikTok type: slideshow.")
        content = content_videos, content_images = [], []
        for get_slides in SLIDE_PROVIDERS:
            if content := await get_slides(info):
                content_videos, content_images = content
                if content_images:
                    return TikTokMedia(**info, content=[*content_videos, *content_images])
            log.info("Trying another API...")

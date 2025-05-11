"""Instagram module"""

import asyncio
import hashlib
import random
import re
import time

from urllib.parse import unquote

# parse json
import orjson

# structured logging
import structlog

# beautiful soup
from bs4 import BeautifulSoup

# deobfuscate js response
from yoiyoi.api.dehunter import dehunter

# InstaMedia namedtuple
from yoiyoi.api.namedtuples import InstaMedia

# request helpers
from yoiyoi.extra.request_helpers import (
    FAKE_HEADERS,
    get_content_extension,
    get_content_name,
    make_request,
)

# get logger
log = structlog.get_logger(__name__)

# instagram queue
ig_queue = asyncio.Queue(maxsize=1)

# regex
REGEX_CLIPDOWNAPP = re.compile(r"ClipDown\.App_(?P<name>[\w\-]+)\.(?P<extension>\w{3,4})")
REGEX_SNAPINSTATO = re.compile(r"SnapInsta\.to_(?P<name>[\w\-]+)\.(?P<extension>\w{3,4})")
REGEX_DOWNRORG = re.compile(r"\/(?P<name>[\w\-]+)\.(?P<extension>\w{3,4})\?")
REGEX_IGRAM = re.compile(r"%2F(?P<name>[\w\-]+)\.(?P<extension>\w{3,4})%3F")

IGRAM = [
    (1742201548873, "aaeaf2805cea6abef3f9d2b6a666fce62fd9d612a43ab772bb50ce81455112e0"),
    (1740129810449, "3526501d956b1c95459de077386711c0529330544d2d57ad6781cc33fa03c7a3"),
]


async def get_links_igramworld(link: str) -> list[InstaMedia]:
    """Gets links from igram.world.

    Args:
        link (str): instagram link.

    Returns:
        list[InstaMedia]: list of instagram media.
    """
    log.info("API: IGram.World.")
    results = []
    # api info
    base = "igram.world"
    origin = f"https://{base}"
    api = f"https://api.{base}/api/convert"

    igram_timestamp, igram_key = random.choice(IGRAM)
    current_timestamp = str(int(time.time() * 1000))
    combined = link + str(current_timestamp) + igram_key

    try:
        hash_obj = hashlib.sha256()
        hash_obj.update(combined.encode("utf-8"))
        secret_string = hash_obj.hexdigest().lower()
    except Exception as ex:
        log.error("Error computing SHA256 hash: %s.", ex)
        return results
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": origin,
            "Connection": "keep-alive",
            "Referer": origin,
        },
        json={
            "url": link,
            "ts": current_timestamp,
            "_ts": igram_timestamp,
            "_tsc": "0",
            "_s": secret_string,
        },
        follow_redirects=True,
        proxy=True,
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return results
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return results
        if not info:
            log.warning("IGram returned no content.")
            return results
        if not isinstance(info, list):
            info = [info]
        for media in info:
            if not (media_url_info := media.get("url")):
                log.warning("Couldn't get content.")
                continue
            media_thumb = media.get("thumb")
            if media_url_info and (content := media_url_info[0]):
                media_ext = content["ext"]
                media_url = content["url"]
                name = await get_content_name(media_url, REGEX_IGRAM, "name")
                results.append(
                    InstaMedia(
                        link,
                        media_thumb,
                        media_url,
                        "video" if media_ext == "mp4" else "image",
                        name,
                    ),
                )
    return results


async def get_links_downr(link: str) -> list[InstaMedia]:
    """Gets links from downr.org.

    Args:
        link (str): instagram link.

    Returns:
        list[InstaMedia]: list of instagram media.
    """
    log.info("API: downr.")
    results = []
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
        json={"url": link},
        follow_redirects=True,
        proxy=True,
    ):
        # check response
        if response.is_error:
            log.warning("Request to API failed: %s.", response)
            log.debug("Response: %s", response.content)
            return results
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return results
        if info["error"]:
            log.warning("downr returned error: %r.", response.content)
            return results
        log.debug("downr info: %s.", info)
        url_thumb = info.get("thumbnail")
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
                    name = await get_content_name(media["url"], REGEX_DOWNRORG, "name")
                    results.append(
                        InstaMedia(
                            link,
                            url_thumb,
                            media["url"],
                            "video",
                            name,
                        ),
                    )
    return results


async def get_links_snapinstato(link: str) -> list[InstaMedia]:
    """Gets links from SnapInsta.to.

    Args:
        link (str): instagram link.

    Returns:
        list[InstaMedia]: list of instagram media.
    """
    log.info("API: SnapInsta.to.")
    results = []
    # api info
    base = "https://snapinsta.to"
    api = f"{base}/api/ajaxSearch"
    # send request
    if token_response := await make_request(
        url=f"{base}/api/userverify",
        headers={
            **FAKE_HEADERS,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": base,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": base,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        },
        data={"url": link},
        proxy=True,
    ):
        # check response
        if token_response.is_error:
            return results
        log.debug("Got token.")
        try:
            info = orjson.loads(token_response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json token: %r.", token_response.content)
            return results
        log.debug("JSON: %r.", info)
        if not (token := info.get("token")):
            log.error("Couldn't get token.")
            return results
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Origin": base,
            "Referer": f"{base}/",
        },
        data={
            "q": link,
            "t": "media",
            "lang": "en",
            "v": "v2",
            "cftoken": token,
        },
        proxy=True,
    ):
        # check response
        if response.is_error:
            return results
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return results
        log.debug("JSON: %r.", info)
        if not (data := info.get("data")):
            log.warning("Couldn't get content.")
            return results  # no info found
        if data.startswith("<ul"):
            html = data
        else:
            result = dehunter(data)
            html = result[0].replace('\\"', '"').replace("\\'", "'")
        # process response
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find_all("div", class_="download-items")
        for media in content:
            divs = media.find_all("div")
            if len(divs) < 2:
                log.info("Not enough divs found.")
                log.debug("Found elements: %s.", divs)
                return results
            # thumbnail
            url_thumb = ""
            if img_thumb := divs[0].img:
                url_thumb = unquote(img_thumb["src"])
            # content
            url_content = ""
            if download_item := divs[-1].a:
                url_content = unquote(download_item["href"])
            name = await get_content_name(url_content, REGEX_SNAPINSTATO, "name")
            results.append(
                InstaMedia(
                    link,
                    url_thumb,
                    url_content,
                    "video" if "Video" in divs[-1].span.text else "image",
                    name,
                ),
            )
    return results


async def get_links_clipdownapp(link: str) -> list[InstaMedia]:
    """Gets links from ClipDown.App.

    Args:
        link (str): instagram link.

    Returns:
        list[InstaMedia]: list of instagram media.
    """
    log.info("API: ClipDown.App.")
    results = []
    # api info
    base = "https://v3.clipdown.app"
    origin = "https://clipdown.app"
    api = f"{base}/api/ajaxSearch"
    # send request
    if token_response := await make_request(
        url=f"{origin}/api/userverify",
        headers={
            **FAKE_HEADERS,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{origin}/en",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": origin,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        },
        data={"url": link},
        proxy=True,
    ):
        # check response
        if token_response.is_error:
            return results
        log.debug("Got token.")
        try:
            info = orjson.loads(token_response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json token: %r.", token_response.content)
            return results
        log.debug("JSON: %r.", info)
        if not (token := info.get("token")):
            log.error("Couldn't get token.")
            return results
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Origin": origin,
            "Referer": f"{origin}/",
        },
        data={
            "q": link,
            "t": "media",
            "lang": "en",
            "v": "v2",
            "cftoken": token,
        },
        proxy=True,
    ):
        # check response
        if response.is_error:
            return results
        log.debug("Request to API succeeded.")
        try:
            info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return results
        log.debug("JSON: %r.", info)
        if not (data := info.get("data")):
            log.warning("Couldn't get content.")
            return results  # no info found
        if data.startswith("<ul"):
            html = data
        else:
            result = dehunter(data)
            html = result[0].replace('\\"', '"').replace("\\'", "'")
        # process response
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find_all("div", class_="download-items")
        for media in content:
            divs = media.find_all("div")
            if len(divs) < 2:
                log.info("Not enough divs found.")
                log.debug("Found elements: %s.", divs)
                return results
            # thumbnail
            url_thumb = ""
            if img_thumb := divs[0].img:
                url_thumb = unquote(img_thumb["src"])
            # content
            url_content = ""
            if download_item := divs[-1].a:
                url_content = unquote(download_item["href"])
            name = await get_content_name(url_content, REGEX_CLIPDOWNAPP, "name")
            results.append(
                InstaMedia(
                    link,
                    url_thumb,
                    url_content,
                    "video" if "Video" in divs[-1].span.text else "image",
                    name,
                ),
            )
    return results


async def get_instagram_links(link: str) -> list[InstaMedia]:
    """Gets links for media using provided by link.

    Args:
        link (str): instagram link.

    Returns:
        list[InstaMedia]: list of instagram media.
    """
    for get_links in (
        get_links_downr,  # good for single video
        get_links_igramworld,  # best
        get_links_snapinstato,  # okay
        get_links_clipdownapp,  # okay
    ):
        if content := await get_links(link):
            return content
        log.info("Trying another API...")
    else:
        return []

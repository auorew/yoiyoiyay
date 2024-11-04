"""Instagram module"""

import asyncio
import logging
import re

from random import getrandbits
from urllib.parse import unquote

# parse json
import orjson

# beautiful soup
from bs4 import BeautifulSoup

# deobfuscate js response
from yoiyoi.api.dehunter import dehunter

# InstaMedia namedtuple
from yoiyoi.api.namedtuples import InstaMedia

# request helpers
from yoiyoi.extra.request_helpers import FAKE_HEADERS, get_content_name, make_request

# get logger
log = logging.getLogger(__name__)

# instagram queue
ig_queue = asyncio.Queue(maxsize=1)

# regex
REGEX_SNAPINSTA = re.compile(r"(?P<name>(_video_\w+)|([0-9_n]+))\.\w{3,4}")
REGEX_SAVEINSTA = re.compile(r"_?(?P<name>[0-9_n]+)\.\w{3,4}[^\w_]")
REGEX_TITLE_DOWNLOAD = re.compile(r"^Download ")


async def get_snapinsta_links(link: str) -> list[InstaMedia]:
    log.info("API: Snapinsta.")
    results = []
    # api info
    base = "https://snapinsta.app"
    api = f"{base}/action2.php"
    # get token
    token = ""
    if response := await make_request(url=base, method="GET"):
        # check response
        if response.is_error:
            return results
        for el in BeautifulSoup(response.content, "html.parser").find_all(
            "input", {"name": "token"}
        ):
            if token := el["value"]:
                log.debug("Got token.")
    if not token:
        return results
    # form request
    boundary = 29 * "-" + str(getrandbits(99))
    data = (
        (boundary + "\r\n").join(
            [
                "",
                f'Content-Disposition: form-data; name="url"\r\n\r\n{link}\r\n',
                'Content-Disposition: form-data; name="action"\r\n\r\npost\r\n',
                'Content-Disposition: form-data; name="lang"\r\n\r\n\r\n',
                f'Content-Disposition: form-data; name="token"\r\n\r\n{token}\r\n',
            ]
        )
        + boundary
        + "--\r\n"
    )
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": f"multipart/form-data; boundary={boundary[2:]}",
            "Origin": base,
            "Referer": f"{base}/",
        },
        data=data,
        referer=base,
        proxy=True,
    ):
        # check response
        if response.is_error:
            return results
        log.debug("Request to API succeeded.")
        result = dehunter(response.content)
        log.debug("Result: %s.", result[1])
        if not result[1]["status"].startswith("success"):
            return results
        # process response
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find_all("div", class_="download-content")
        for media in content:
            url = media.find("a", {"data-event": "click_download_btn"})
            name = await get_content_name(url["href"], REGEX_SNAPINSTA, "name")
            if len(name) > 1:
                name = name[1:].replace("_video_dashinit", "")
            results.append(
                InstaMedia(
                    link,
                    media.find("img", {"alt": "Preview"})["src"],
                    url["href"],
                    "video" if "Video" in url.text else "image",
                    name,
                ),
            )
    return results


async def get_saveinsta_links(link: str) -> list[InstaMedia]:
    log.info("API: Saveinsta.")
    results = []
    # api info
    base = "https://saveinsta.app"
    ref = f"{base}/en1"
    api = "https://v3.saveinsta.app/api/ajaxSearch"
    # get token
    k_exp, k_token = "", ""
    if response := await make_request(url=ref, method="GET"):
        # check response
        if response.is_error:
            return results
        for script in BeautifulSoup(response.content, "html.parser").find_all("script"):
            if script.text.startswith("var k_url"):
                for token in script.text.split(","):
                    if token.startswith("k_exp"):
                        k_exp = token.split("=")[1].replace('"', "")
                    if token.startswith("k_token"):
                        k_token = token.split("=")[1].replace('"', "")
    if not (k_exp and k_token):
        return results
    # send request
    if response := await make_request(
        url=api,
        headers={
            **FAKE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": base,
            "Referer": f"{base}/",
        },
        data={
            "reCaptchaToken": "",
            "reCaptchaType": "",
            "k_exp": k_exp,
            "k_token": k_token,
            "q": link,
            "t": "media",
            "lang": "en",
            "v": "v2",
        },
        referer=base,
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
        if info["status"] != "ok" or (
            info.get("mess") and info["mess"].startswith("Error")
        ):
            return results
        result = dehunter(info["data"])
        # process response
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find_all("div", class_="download-items")
        for media in content:
            urls = media.find_all("a", title=REGEX_TITLE_DOWNLOAD)
            if len(urls) < 2:
                log.info("Not enough URLs found.")
                log.debug("Found elements: %s.", urls)
                return results
            name = await get_content_name(urls[0]["href"], REGEX_SAVEINSTA, "name")
            results.append(
                InstaMedia(
                    link,
                    urls[0]["href"],
                    urls[1]["href"],
                    "video" if "Video" in urls[1]["title"] else "image",
                    name,
                ),
            )
    return results


async def get_igdownloader_links(link: str) -> list[InstaMedia]:
    """Gets links from IG Downloader.

    Args:
        link (str): instagram link.

    Returns:
        list[InstaMedia]: list of instagram media.
    """
    log.info("API: IG Downloader.")
    results = []
    # api info
    base = "https://v3.clipdown.app"
    origin = "https://clipdown.app"
    api = f"{base}/api/ajaxSearch"
    # send request
    if response := await make_request(
        url=api,
        headers={**FAKE_HEADERS, "Origin": origin, "Referer": f"{origin}/"},
        data={
            "q": link,
            "t": "media",
            "lang": "en",
            "v": "v2",
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
        result = dehunter(data)
        # process response
        html = result[0].replace('\\"', '"').replace("\\'", "'")
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find_all("div", class_="download-items")
        for media in content:
            urls = media.find_all("a", title=REGEX_TITLE_DOWNLOAD)
            if len(urls) < 2:
                log.info("Not enough URLs found.")
                log.debug("Found elements: %s.", urls)
                return results
            url_thumb = unquote(urls[0]["href"])
            url_content = unquote(urls[1]["href"])
            name = await get_content_name(url_thumb, REGEX_SAVEINSTA, "name")
            results.append(
                InstaMedia(
                    link,
                    url_thumb,
                    url_content,
                    "video" if "Video" in urls[1]["title"] else "image",
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
        # get_snapinsta_links,  # good
        # get_saveinsta_links,  # good
        get_igdownloader_links,  # okay
    ):
        if content := await get_links(link):
            return content
        log.info("Trying another API...")
    else:
        return []

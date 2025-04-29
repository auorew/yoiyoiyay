from typing import Optional

# structured logging
import structlog

# html parsing
from bs4 import BeautifulSoup

# making requests
from yoiyoi.extra.request_helpers import make_request

# setup logger
log = structlog.get_logger(__name__)


async def expand_with_urlex(link: str) -> Optional[str]:
    if response := await make_request(
        url="https://urlex.org/",
        data={"s": link},
        proxy=True,
    ):
        # check response
        if response.is_error:
            return
        log.debug("URLEX: Request to API succeeded.")
        # check response
        soup = BeautifulSoup(response.text, "html.parser")
        expanded_urls = soup.find_all("a", {"rel": "external nofollow"})
        if not expanded_urls:
            log.debug("URLEX: No valid response.")
            return
        # process response
        if expanded_url := expanded_urls[0].attrs.get("href", None):
            log.debug("URLEX: %r.", expanded_url)
            return expanded_url
        log.debug("URLEX: No URL.")


async def expand_with_expandurl(link) -> dict:
    if response := await make_request(
        "https://www.expandurl.net/",
        data={"url": link},
    ):
        # check response
        if response.is_error:
            return
        log.debug("ExpandURL: Request to API succeeded.")
        # check response
        soup = BeautifulSoup(response.text, "lxml")
        if not (expanded_url := soup.find("div", string="Long URL:")):
            log.debug("ExpandURL: No valid response.")
            return
        # process response
        if expanded_url.parent.a:
            log.debug("ExpandURL: %r.", expanded_url.parent.a.text)
            return expanded_url.parent.a.text
        log.debug("ExpandURL: No URL.")

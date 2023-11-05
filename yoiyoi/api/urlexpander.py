import logging

from typing import Optional

# html parsing
from bs4 import BeautifulSoup

# making requests
from ..extra.request_helpers import make_request

# setup logger
log = logging.getLogger(__name__)


async def expand_with_urlex(link: str) -> Optional[str]:
    if response := await make_request(
        url="https://urlex.org/",
        data={"s": link},
        proxy=True,
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        # check response
        soup = BeautifulSoup(response.text, "html.parser")
        expanded_urls = soup.find_all("a", {"rel": "external nofollow"})
        if not expanded_urls:
            return
        # process response
        if expanded_url := expanded_urls[0].attrs.get("href", None):
            return expanded_url


async def expand_with_expandurl(link) -> dict:
    if response := await make_request(
        "https://www.expandurl.net/expand",
        data={"url": link},
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        # check response
        soup = BeautifulSoup(response.text, "lxml")
        if not (expanded_url := soup.find("div", string="Long URL:")):
            return
        # process response
        if expanded_url.parent.a:
            return expanded_url.parent.a.text


async def expand_with_checkshorturl(link) -> dict:
    if response := await make_request(
        "https://checkshorturl.com/",
        data={"links": link},
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        # check response
        soup = BeautifulSoup(response.text, "lxml")
        if not (expanded_url := soup.find("p", string="Long URL")):
            return
        # process response
        if expanded_url.next_sibling.a:
            return expanded_url.next_sibling.a.text

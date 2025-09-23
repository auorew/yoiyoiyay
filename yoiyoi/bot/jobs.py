"""Bot Jobs"""

import asyncio
import random
import ssl

# typing for type hints
from typing import Iterable, Optional

# http requests
import httpx

# structured logging
import structlog

# beautiful soup
from bs4 import BeautifulSoup

# telegram core bot api extension
from telegram.ext import ContextTypes

# get proxy dict and constant
from yoiyoi.extra import PROXY, PROXY_CID, PROXY_LIMIT, PROXY_SET, PROXY_TIMEOUT

# get fake headers & retry requets
from yoiyoi.extra.request_helpers import FAKE_HEADERS

# settings
from yoiyoi.extra.settings import bot_settings

# setup logger
log = structlog.get_logger(__name__)


class GetProxy:
    free_proxy_sources = (
        "https://www.sslproxies.org/",
        "https://free-proxy-list.net/",
    )
    test_links = (
        "https://www.tiktok.com/@osudailybanger/video/7167401459322080518",
        "https://www.tiktok.com/@jeesejuice/video/7060481973659405570",
        "https://www.tiktok.com/@perrikaryal/video/7234874564365339930",
        "https://www.tiktok.com/@reo5419233/video/7218525971639553282",
        "https://www.tiktok.com/@giftgenius/video/7323685510692523269",
        "https://www.tiktok.com/@anthonysistilli/video/7365519366001315077",
        "https://www.tiktok.com/@shonci/video/7324459656825294086",
    )

    def __init__(
        self,
        *,
        country: Optional[Iterable[str]] = None,
        timeout: float = 1,
        limit: int = 10,
    ):
        self.country = set(country) if country else None
        self.timeout = timeout
        self.limit = limit
        self.working_proxy = set()
        self.proxy_list = set()
        self.semaphore = asyncio.Semaphore(self.limit)

    async def get(self):
        log.debug("GetProxy: Clearing working proxy and proxy list...")
        self.working_proxy.clear()
        self.proxy_list.clear()

        log.debug("GetProxy: Getting new proxies...")
        await self.get_proxy()

        log.debug("GetProxy: Returning new proxies...")
        return self.working_proxy

    async def test_proxy(
        self,
        proxy_protocol: str,
        proxy_addr: str,
        proxy_port: str | int,
    ):
        async with self.semaphore:
            try:
                proxy = f"{proxy_protocol}://{proxy_addr}:{proxy_port}"
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    proxy=proxy,
                ) as shared_client:
                    if (
                        main_response := await shared_client.get(
                            random.choice(self.test_links),
                            headers=FAKE_HEADERS,
                        )
                    ) and main_response.is_error:
                        raise httpx.RequestError("Tiktok: Couldn't reach")
                    self.working_proxy.add(proxy)
                    self.proxy_list.add(proxy)
                    return
            except (
                ValueError,
                ssl.SSLError,
                httpx.ProxyError,
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
                httpx.RequestError,
            ):
                return
            except Exception as ex:
                log.warning(
                    "GetProxy: Test proxy exception. %s: %s.",
                    ex.__class__.__name__,
                    ex,
                )
                return

    async def get_proxy(self):
        variants = set()
        try:
            async with httpx.AsyncClient() as client:
                for source in self.free_proxy_sources:
                    page = await client.get(source, timeout=5, follow_redirects=True)
                    if page.is_error:
                        continue
                    soup = BeautifulSoup(page.text, "html.parser")
                    if not (container := soup.find_all("div", {"class": "fpl-list"})):
                        continue
                    if not (table := container[0].table):
                        continue
                    if not (tbody := table.tbody):
                        continue
                    for row in tbody:
                        (
                            ip,
                            port,
                            country_code,
                            country_name,
                            anon,
                            google,
                            https,
                            checked,
                        ) = (el.text for el in row.find_all("td"))
                        if https == "yes":
                            variants.add(("http", ip, port))

                tasks = []
                for variant in variants:
                    if not self.country or variant[2] in self.country:
                        tasks.append(asyncio.create_task(self.test_proxy(*variant)))
                await asyncio.wait(tasks)

        except Exception as ex:
            log.warning(
                "GetProxy: Request to proxy API or parsing failed. %s: %s.",
                ex.__class__.__name__,
                ex,
                exc_info=True,
            )


proxy_getter = GetProxy(country=PROXY_CID, timeout=PROXY_TIMEOUT, limit=PROXY_LIMIT)


async def get_proxy(
    _: ContextTypes.DEFAULT_TYPE,
):
    """Get working proxy or nothing

    Args:
        _ (ContextTypes): callback context (not used)
    """
    if bot_settings.proxy_url:
        proxy_url = str(bot_settings.proxy_url)
        log.info("Using proxy: %s.", proxy_url)
        PROXY["active"] = proxy_url
    proxy_set = await proxy_getter.get()
    log.debug("GetProxy: Updating proxies...")
    PROXY_SET.update(proxy_set)
    if PROXY_SET:
        log.debug("GetProxy: Proxies: %s.", ", ".join(proxy_getter.proxy_list))
        if not PROXY["active"]:
            proxy_url = PROXY_SET.pop()
            log.info("Using proxy: %s.", proxy_url)
            PROXY["active"] = proxy_url
    else:
        log.debug("GetProxy: No proxies.")


async def health_checker(
    _: ContextTypes.DEFAULT_TYPE,
):
    """Ping the specified instance and log the result"""
    if not bot_settings.health_check_url:
        return

    try:
        hcu = str(bot_settings.health_check_url)
        async with httpx.AsyncClient(timeout=5) as client:
            if (response := await client.get(hcu, headers=FAKE_HEADERS)).is_error:
                log.warning(
                    "PingInstance: failed to reach %s. Status: %s",
                    hcu,
                    response.status_code,
                )
            else:
                log.debug(
                    "PingInstance: successfully reached %s. Status: %s",
                    hcu,
                    response.status_code,
                )
    except Exception as exception:
        log.warning(
            "PingInstance: exception %s: %s.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
        )

"""Bot Jobs"""

import asyncio
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
    free_proxy_api = (
        "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&proxy_format=protocolipport&format=text",
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
        self.working_proxy.clear()
        self.proxy_list.clear()
        await self.get_proxy()
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
                            "https://m.tiktok.com/v/7060481973659405570",
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
                    "Test proxy exception. %s: %s.",
                    ex.__class__.__name__,
                    ex,
                )
                return

    async def get_proxy(self):
        variants = set()
        try:
            async with httpx.AsyncClient() as client:
                for source in self.free_proxy_sources:
                    page = await client.get(source, follow_redirects=True)
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
                for source in self.free_proxy_api:
                    page = await client.get(
                        source,
                        headers={
                            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:142.0) "
                            "Gecko/20100101 Firefox/142.0",
                            "Accept": "text/html,application/xhtml+xml,application/xml;"
                            "q=0.9,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.5",
                            "Accept-Encoding": "gzip, deflate, br, zstd",
                            "DNT": "1",
                            "Sec-GPC": "1",
                            "Connection": "keep-alive",
                            "Upgrade-Insecure-Requests": "1",
                            "Sec-Fetch-Dest": "document",
                            "Sec-Fetch-Mode": "navigate",
                            "Sec-Fetch-Site": "none",
                            "Sec-Fetch-User": "?1",
                            "Priority": "u=0, i",
                            "TE": "trailers",
                        },
                        follow_redirects=True,
                    )
                    if page.is_error:
                        continue
                    for proxy in page.text.split():
                        variants.add(tuple(proxy.replace("//", "").split(":")))

                tasks = []
                for variant in variants:
                    if not self.country or variant[2] in self.country:
                        tasks.append(asyncio.create_task(self.test_proxy(*variant)))
                await asyncio.wait(tasks)
        except Exception as ex:
            log.warning(
                "Request to proxy API or parsing failed. %s: %s.",
                ex.__class__.__name__,
                ex,
            )


proxy_getter = GetProxy(country=PROXY_CID, timeout=PROXY_TIMEOUT, limit=PROXY_LIMIT)


async def get_proxy(
    context: ContextTypes.DEFAULT_TYPE,
):
    """Get working proxy or nothing

    Args:
        _ (ContextTypes): callback context (not used)
    """
    if bot_settings.proxy_url:
        PROXY["active"] = str(bot_settings.proxy_url)
    PROXY_SET.update(await proxy_getter.get())
    if PROXY_SET and not PROXY["active"]:
        log.debug("GetProxy: Proxies: %s.", ", ".join(proxy_getter.proxy_list))
        PROXY["active"] = PROXY_SET.pop()
    else:
        log.debug("GetProxy: No proxies.")


async def health_checker(
    context: ContextTypes.DEFAULT_TYPE,
):
    """Ping the specified instance and log the result"""
    if not bot_settings.health_check_url:
        return

    try:
        hcu = str(bot_settings.health_check_url)
        async with httpx.AsyncClient(timeout=5) as client:
            if (response := await client.get(hcu, headers=FAKE_HEADERS)).is_error:
                log.warning(
                    "PingInstance: Failed to reach %s. Status: %s",
                    hcu,
                    response.status_code,
                )
            else:
                log.debug(
                    "PingInstance: Successfully reached %s. Status: %s",
                    hcu,
                    response.status_code,
                )
    except Exception as ex:
        log.warning("PingInstance: Exception %s: %s.", ex.__class__.__name__, ex)

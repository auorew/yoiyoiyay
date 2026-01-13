"""Proxy module"""

import asyncio
import random
import ssl

# typing for type hints
from typing import Iterable, Optional

# http requests
import httpx

# structured logging
import structlog

# parsing html
from bs4 import BeautifulSoup, SoupStrainer

# get proxy dict and constant
from yoiyoi.extra import PROXY_CID, PROXY_LIMIT, PROXY_TIMEOUT

# get fake headers
from yoiyoi.extra.request_helpers import get_fake_headers

# bot settings
from yoiyoi.extra.settings import bot_settings

log = structlog.get_logger(__name__)


class ProxyManager:
    def __init__(self, static_url: Optional[str] = None):
        self.active: Optional[str] = None
        self.is_static: bool = False
        if static_url is not None:
            self.active = str(static_url)
            self.is_static = True
        self.pool: list = []
        self.log: structlog.BoundLogger = log.bind(app="proxy_manager")
        self._lock = asyncio.Lock()
        self.request_attempts: int = 0

    async def rotate(self):
        """Thread-safe rotation. Does nothing if proxy is static."""
        if self.is_static:
            return self.active

        async with self._lock:
            self.request_attempts += 1
            if self.pool:
                self.active = self.pool.pop()
                self.log.info("Proxy rotated.", new_proxy=self.active)
            else:
                self.active = None
                self.log.warning("Proxy pool empty. Continuing without proxy.")
            return self.active

    def reset_attempts(self):
        """Resets counter after a successful request."""
        self.request_attempts = 0

    def update_pool(self, new_proxies: set):
        """Job calls this to add fresh tested proxies."""
        if self.is_static:
            return
        new_items = [p for p in new_proxies if p not in self.pool and p != self.active]
        self.pool.extend(new_items)

    def invalidate(self):
        """Clears the active proxy if it fails."""
        self.active = None


class ProxyGetter:
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
        self.log: structlog.BoundLogger = log.bind(app="proxy_getter")
        self._semaphore = None

    @property
    def semaphore(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.limit)
        return self._semaphore

    async def get(self):
        self._semaphore = None

        self.log.debug("Clearing working proxy and proxy list...")
        self.working_proxy.clear()
        self.proxy_list.clear()

        self.log.debug("Getting new proxies...")
        await self.get_proxy()

        self.log.debug("Returning new proxies...")
        return self.working_proxy

    def get_sync_wrapper(self) -> set:
        return asyncio.run(self.get())

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
                            headers=get_fake_headers(),
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
                self.log.warning(
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
                    page = await client.get(source, timeout=5, follow_redirects=True)
                    if page.is_error:
                        continue
                    soup = BeautifulSoup(
                        markup=page.content,
                        features="lxml",
                        parse_only=SoupStrainer("div", {"class": "fpl-list"}),
                    )
                    for container in soup:
                        if not (table := container.table) or not (tbody := table.tbody):
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
                    # delete html tree
                    soup.decompose()
                    # close response
                    await page.aclose()
                # now check every proxy
                async with asyncio.TaskGroup() as tg:
                    for variant in variants:
                        if not self.country or variant[2] in self.country:
                            tg.create_task(self.test_proxy(*variant))

        except Exception as ex:
            self.log.warning(
                "Request to proxy API or parsing failed. %s: %s.",
                ex.__class__.__name__,
                ex,
                exc_info=True,
            )


proxy_manager = ProxyManager(static_url=bot_settings.proxy_url)
proxy_getter = ProxyGetter(country=PROXY_CID, timeout=PROXY_TIMEOUT, limit=PROXY_LIMIT)

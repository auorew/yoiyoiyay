"""Bot Jobs"""

import asyncio
import ssl

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
        country: list[str] | set[str] = None,
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
                    page = await client.get(source)
                    if page.is_error:
                        continue
                    soup = BeautifulSoup(page.text, "html.parser")
                    container = soup.find_all("div", {"class": "fpl-list"})
                    for row in container[0].table.tbody:
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
                    page = await client.get(source)
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


proxy_getter = GetProxy(PROXY_CID, PROXY_TIMEOUT, PROXY_LIMIT)


async def get_proxy(
    context: ContextTypes.DEFAULT_TYPE,
):
    """Get working proxy or nothing

    Args:
        _ (ContextTypes): callback context (not used)
    """
    PROXY_SET.update(await proxy_getter.get())
    if PROXY_SET:
        log.debug("GetProxy: Proxies: %s.", ", ".join(proxy_getter.proxy_list))
        PROXY["active"] = PROXY_SET.pop()
    else:
        log.debug("GetProxy: No proxies.")

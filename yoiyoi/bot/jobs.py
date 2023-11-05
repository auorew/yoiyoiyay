"""Bot Jobs"""
import asyncio
import logging
import os
import ssl

# http requests
import httpx

# parse json
import orjson

# beautiful soup
from bs4 import BeautifulSoup

# telegram core bot api extension
from telegram.ext import CallbackContext

# get proxy dict and constant
from ..extra import PROXY, PROXY_CID, PROXY_LIMIT, PROXY_SET, PROXY_TIMEOUT

# get fake headers & retry requets
from ..extra.request_helpers import FAKE_HEADERS, make_request

# setup logger
log = logging.getLogger(__name__)


class GetProxy:
    free_proxy_sources = (
        "https://www.sslproxies.org/",
        "https://free-proxy-list.net/",
    )
    test_url = "https://www.google.com"

    def __init__(
        self,
        country: list[str] = None,
        timeout: float = 0.5,
        limit: int = None,
    ):
        self.country = country
        self.timeout = timeout
        self.limit = limit
        self.working_proxy = set()
        self.proxy_list = set()

    async def get(self):
        self.working_proxy.clear()
        self.proxy_list.clear()
        await self.get_proxy()
        return self.working_proxy

    async def test_proxy(self, proxy_addr, proxy_port, proxy_country):
        try:
            proxy = f"http://{proxy_addr}:{proxy_port}"
            async with httpx.AsyncClient(
                proxies=proxy,
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                if (
                    main_response := await client.get(
                        "https://m.tiktok.com/v/7060481973659405570",
                        headers=FAKE_HEADERS,
                    )
                ) and main_response.is_error:
                    raise httpx.RequestError("Tiktok: Couldn't reach")
                if (
                    api_response := await client.post(
                        "https://api.tikmate.app/api/lookup",
                        headers={
                            **FAKE_HEADERS,
                            "Content-Type": "application/x-www-form-urlencoded;"
                            " charset=UTF-8",
                            "Referer": "https://tikmate.app/",
                        },
                        data={"url": "https://m.tiktok.com/v/7060481973659405570"},
                    )
                ) and api_response.is_error:
                    raise httpx.RequestError("Tiktok: Couldn't get")
                log.trace("GetProxy: Tiktok: %r.", orjson.loads(api_response.content))
                self.working_proxy.add(proxy)
                self.proxy_list.add(f"{proxy} [{proxy_country}]")
                return
        except httpx.ConnectTimeout:
            log.trace("GetProxy: Tiktok: Timed out.")
        except httpx.ConnectError:
            log.trace("GetProxy: Tiktok: Couldn't connect.")
        except httpx.ReadTimeout:
            log.trace("GetProxy: Tiktok: Couldn't read.")
        except httpx.RequestError as ex:
            log.trace("GetProxy: %s.", ex)
        except orjson.JSONDecodeError:
            log.trace("GetProxy: Tiktok: Couldn't decode.")
        except ssl.SSLError:
            log.trace("GetProxy: SSL verification failed.")
        except Exception as ex:
            log.trace("GetProxy: [%s] %s.", type(ex), ex)

    async def get_proxy(self):
        try:
            async with httpx.AsyncClient() as client:
                for source in self.free_proxy_sources:
                    page = await client.get(source)
                    soup = BeautifulSoup(page.text, "html.parser")
                    container = soup.find_all("div", {"class": "fpl-list"})
                    variants = set()
                    for row in container[0].table.tbody:
                        variants.add(tuple(row.find_all(text=True)[:3]))
                tasks = []
                for row_id, variant in enumerate(variants, 1):
                    if not self.country or variant[2] in self.country:
                        tasks.append(asyncio.create_task(self.test_proxy(*variant)))
                    if self.limit and row_id % self.limit == 0:
                        await asyncio.wait(tasks)
                await asyncio.wait(tasks)
        except Exception as ex:
            log.warning(
                "Request to proxy API or parsing failed. %s: %s.",
                ex.__class__.__name__,
                ex,
            )


proxy_getter = GetProxy(PROXY_CID, PROXY_TIMEOUT, PROXY_LIMIT)


async def get_proxy(_: CallbackContext):
    """Get working proxy or nothing

    Args:
        _ (CallbackContext): callback context (not used)
    """
    PROXY_SET.update(await proxy_getter.get())
    if PROXY_SET:
        log.debug("GetProxy: Proxies: %s.", ", ".join(proxy_getter.proxy_list))
        PROXY["https://"] = PROXY_SET.pop()
    else:
        log.debug("GetProxy: No proxies.")


async def ping_yaminui(_: CallbackContext):
    """Ping yaminui bot

    Args:
        _ (CallbackContext): callback context (not used)
    """
    response = await make_request(
        os.environ["YAMINUI_LINK"],
        method="POST",
        headers={**FAKE_HEADERS, "Content-Type": "application/json"},
        data=orjson.dumps({}),
    )
    log.debug("Ping to yaminui bot: %r.", response)


async def ping_resizer(_: CallbackContext):
    """Ping resizer bot

    Args:
        _ (CallbackContext): callback context (not used)
    """
    response = await make_request(
        os.environ["RESIZER_LINK"],
        method="GET",
    )
    log.debug("Ping to resizer bot: %r.", response)

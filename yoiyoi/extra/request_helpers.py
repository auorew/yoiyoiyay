"""Request helpers"""

import logging
import re
import tempfile

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional
from urllib.parse import unquote

# http requests
import httpx

# file extension
import magic

# async caching
from aiocache import cached

# httpx exceptions
from httpx import ConnectTimeout, ProxyError, ReadError, ReadTimeout, RemoteProtocolError

# pyrogram exceptions
from pyrogram.errors import FloodWait

# telegram exceptions
from telegram.error import RetryAfter

# hardcore retrying
from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt

# link types and other info
from yoiyoi.extra import (
    PROXY,
    PROXY_SET,
    RETRY_MAX_TIMEOUT,
    RETRY_MAX_TRIES,
    RETRY_PROXY_MAX_TIMEOUT,
)

# get logger
log = logging.getLogger(__name__)

# fake headers
FAKE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

# pixiv headers
PIXIV_HEADERS = {
    "user-agent": "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)",
    "app-os-version": "14.6",
    "app-os": "ios",
    "referer": "https://www.pixiv.net/",
    "referrer-policy": "strict-origin-when-cross-origin",
}

# regex
INVALID_CHARS = re.compile(r"[\/\\\?\%\*\:\|\"\<\>]")


def wait_fixed_time(retry_state: RetryCallState) -> int:
    """Waits fixed time before next retry depending on exception

    Args:
        retry_state (RetryCallState): retry state

    Returns:
        int: time to wait
    """
    if not (exception := retry_state.outcome.exception()):
        return RETRY_MAX_TIMEOUT
    # telegram retry after error
    if isinstance(exception, RetryAfter):
        log.warning("Telegram limit exceeded: waiting %d s.", exception.retry_after + 1)
        return exception.retry_after + 1
    if isinstance(exception, FloodWait):
        log.warning("Telegram limit exceeded: waiting %d s.", exception.value + 1)
        return exception.value + 1
    # network errors
    if isinstance(
        exception,
        ProxyError | ConnectTimeout | ReadError | ReadTimeout | RemoteProtocolError,
    ):
        # proxy errors
        if (retry_state.kwargs.get("proxy")) and PROXY["active"]:
            log.warning(
                "Connection to proxy [%s] failed, because of %s: %r.",
                PROXY["active"],
                exception.__class__.__name__,
                exception,
            )
            if retry_state.attempt_number == RETRY_MAX_TRIES or not PROXY_SET:
                PROXY["active"] = None
            else:
                PROXY["active"] = PROXY_SET.pop()
            return RETRY_PROXY_MAX_TIMEOUT
        # connection errors
        return RETRY_MAX_TIMEOUT / 5
    log.warning(
        "Retrying request because of %s: %r.",
        exception.__class__.__name__,
        exception,
    )
    # other errors
    return RETRY_MAX_TIMEOUT


def failed_request(retry_state: RetryCallState) -> None:
    """Returns None if request failed

    Args:
        retry_state (RetryCallState): retry state

    Returns:
        None
    """
    return


def retry_request(func):
    """Decorator that retries telegram send function

    Args:
        func (Callable): telegram send function
    """
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(RETRY_MAX_TRIES),
        wait=wait_fixed_time,
        retry_error_callback=failed_request,
    ).wraps(func)


@asynccontextmanager
async def get_async_client(proxy: bool = False):
    try:
        my_proxy = PROXY["active"] if proxy and PROXY["active"] else None
        async with httpx.AsyncClient(proxy=my_proxy) as client:
            yield client
    except Exception as exception:
        log.warning(
            "Failed to get an async httpx client because of %s: %r.",
            exception.__class__.__name__,
            exception,
        )


@retry_request
async def make_request(
    url: str,
    method: str = "POST",
    headers: dict = None,
    follow_redirects: bool = True,
    timeout: int = 15,
    referer: str = None,
    xsrf: str = None,
    cookies: dict = None,
    proxy: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    """Makes request with httpx.AsyncClient

    Args:
        url (str): request url
        method (str, optional): request method. Defaults to "POST".
        headers (dict, optional): request headers. Defaults to None.
        follow_redirects (bool, optional): follow redirecting. Defaults to True.
        timeout (int, optional): request timeout. Defaults to 10.
        referer (str, optional): request referer to get cookies from. Defaults to None.
        xsrf (str, optional): extract xsrf token. Defaults to None.
        cookies (dict, optional): request cookies. Defaults to None.
        proxy (bool, optional): use proxy for request. Defaults to False.

    Returns:
        httpx.Response: response
    """
    my_proxy = PROXY["active"] if proxy and PROXY["active"] else None
    async with httpx.AsyncClient(proxy=my_proxy) as client:
        if not headers:
            headers = FAKE_HEADERS.copy()
        # get cookies in session
        cookies = cookies if cookies else {}
        if referer:
            cookies.update(
                (
                    await client.get(
                        url=referer,
                        headers=headers,
                        follow_redirects=True,
                    )
                ).cookies
            )
        if xsrf:
            headers[xsrf] = unquote(cookies["XSRF-TOKEN"])

        return await client.request(
            method=method,
            url=url,
            headers=headers,
            cookies=cookies if referer or cookies else None,
            follow_redirects=follow_redirects,
            timeout=timeout,
            **kwargs,
        )


@asynccontextmanager
async def stream_response(
    url: str,
    method: str = "POST",
    headers: dict = None,
    follow_redirects: bool = True,
    timeout: int = 15,
    referer: str = None,
    xsrf: str = None,
    cookies: dict = None,
    proxy: bool = False,
    **kwargs: Any,
) -> AsyncIterator[httpx.Response]:
    try:
        async with get_async_client(proxy) as client:
            if not headers:
                headers = FAKE_HEADERS.copy()
            # get cookies in session
            cookies = cookies if cookies else {}
            if referer and (new_cookies := await get_cookies(referer, headers=headers)):
                cookies.update(new_cookies)
            if xsrf:
                headers[xsrf] = unquote(cookies["XSRF-TOKEN"])

            async with client.stream(
                method=method,
                url=url,
                headers=headers,
                cookies=cookies if referer or cookies else None,
                follow_redirects=follow_redirects,
                timeout=timeout,
                **kwargs,
            ) as response:
                yield response
    except Exception as exception:
        log.warning(
            "Failed to stream an httpx response because of %s: %r.",
            exception.__class__.__name__,
            exception,
        )


@asynccontextmanager
async def get_content(url: str, chunk_size: int = 1024, **kwargs) -> AsyncIterator[bytes]:
    try:
        async with stream_response(url, **kwargs) as response:
            yield response.aiter_bytes(chunk_size)
    except Exception as exception:
        log.warning(
            "Failed to get an async httpx client because of %s: %r.",
            exception.__class__.__name__,
            exception,
        )


@retry_request
async def save_file(url: str, method="GET", **kwargs) -> Optional[str]:
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        await write_content_to_file(url, temp_file, method=method, **kwargs)
        return temp_file.name


@retry_request
async def write_content_to_file(
    url: str,
    file: tempfile.NamedTemporaryFile,
    **kwargs,
) -> None:
    async with get_content(url, **kwargs) as content_iterator:
        async for chunk in content_iterator:
            file.write(chunk)


@retry_request
async def get_headers(url: str, **kwargs) -> Optional[httpx.Headers]:
    async with stream_response(url, **kwargs) as response:
        if response.is_success:
            return response.headers


@retry_request
async def get_cookies(url: str, **kwargs) -> Optional[httpx.Cookies]:
    async with stream_response(url, "GET", **kwargs) as response:
        if response.is_success:
            return response.cookies


@cached(ttl=15, key_builder=lambda fn, *a, **kw: a[0])
async def get_content_headers(url: str, **kwargs) -> Optional[httpx.Headers]:
    return (
        # try HEAD request
        await get_headers(url, method="HEAD", **kwargs)
        # try GET request, since HEAD may be forbidden
        or await get_headers(url, method="GET", **kwargs)
    )


@cached(ttl=15, key_builder=lambda fn, *a, **kw: a[0])
async def get_content_size(url: str, headers=FAKE_HEADERS, **kwargs) -> int:
    if file_headers := await get_content_headers(url, headers=headers, **kwargs):
        return int(file_headers.get("Content-Length", 0))
    return 0


@cached(ttl=15, key_builder=lambda fn, *a, **kw: a[0])
async def get_content_name(
    url: str,
    pattern: re.Pattern,
    group: str = "name",
    **kwargs,
) -> str:
    file_name = ""
    if file_headers := await get_content_headers(url, **kwargs):
        if file_name := file_headers.get("Content-Disposition", ""):
            if matched := re.search(pattern, file_name):
                file_name = matched[group]
        elif matched := re.search(pattern, url):
            file_name = matched[group]
    return re.sub(INVALID_CHARS, "", file_name)


@retry_request
async def get_content_type(url: str, mime=True, **kwargs) -> Optional[str]:
    async with get_content(url, **kwargs) as content_iterator:
        chunk = await anext(content_iterator)
        return magic.from_buffer(chunk, mime=mime)


@retry_request
async def get_content_extension(url: str, **kwargs) -> Optional[str]:
    if mime_type := await get_content_type(url, mime=True, **kwargs):
        return mime_type.split("/")[-1]


async def get_file_info(
    url: str,
    size: bool = False,
    pattern: re.Pattern = False,
    group: str = None,
) -> dict:
    info = {}
    if size and (file_size := await get_content_size(url)):
        info["size"] = file_size
    if pattern and group and (file_name := await get_content_name(url, pattern, group)):
        info["name"] = file_name
    return info


@retry_request
async def get_file(url: str, method: str = "GET", **kwargs) -> bytes:
    """Gets file content

    Args:
        url (str): file resource url or file API
        method (str, optional): request method. Defaults to "GET".

    Raises:
        Exception: no file content

    Returns:
        bytes: file content
    """
    response = await make_request(url, method, **kwargs)
    if response and response.is_success and (file := response.content):
        return file
    else:
        raise Exception("No file content was received")

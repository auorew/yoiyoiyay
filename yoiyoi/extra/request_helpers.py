"""Request helpers"""

import re
import tempfile

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional
from urllib.parse import unquote

# http requests
import httpx

# file extension
import magic

# structured logging
import structlog

# async caching
from aiocache import cached

# up-to-date user-agent
from fake_useragent import UserAgent

# httpx exceptions
from httpx import ConnectTimeout, ProxyError, ReadError, ReadTimeout, RemoteProtocolError

# telegram exceptions
from telegram.error import RetryAfter

# hardcore retrying
from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt

# link types and other info
from yoiyoi.extra import (
    DEFAULT_REQUEST_TIMEOUT,
    PROXY,
    PROXY_SET,
    RETRY_MAX_TIMEOUT,
    RETRY_MAX_TRIES,
    RETRY_MIN_TIMEOUT,
    RETRY_PROXY_MAX_TIMEOUT,
    RETRY_PROXY_MAX_TRIES,
)

# get logger
log = structlog.get_logger(__name__)

# init user-agnet generator
ua_generator = UserAgent(browsers=["Chrome", "Edge", "Firefox"])

# fake headers
FAKE_HEADERS = {
    "User-Agent": ua_generator.firefox,
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}


def get_fake_headers():
    ua_string = ua_generator.random
    headers = {
        "User-Agent": ua_string,
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    # Logic for Chromium-based browsers (Chrome/Edge)
    # These MUST have Sec-CH-UA headers to look real
    if "Chrome" in ua_string or "Edg" in ua_string:
        # Extract the major version using a regex
        # e.g., 'Chrome/132.0.0.0' -> '132'
        version_match = re.search(r"(?:Chrome|Edg)/(\d+)", ua_string)
        major_version = version_match.group(1) if version_match else "132"

        brand = "Google Chrome" if "Chrome" in ua_string else "Microsoft Edge"

        headers.update(
            {
                "Sec-Ch-Ua": f'"Not A(Brand";v="99", "{brand}";v="{major_version}", '
                f'"Chromium";v="{major_version}"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            }
        )
    # Logic for Firefox
    elif "Firefox" in ua_string:
        # Firefox does NOT use Sec-CH-UA
        headers.update({})

    return headers


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
        return RETRY_MIN_TIMEOUT
    # telegram retry after error
    if isinstance(exception, RetryAfter):
        log.warning("Telegram limit exceeded: waiting %d s.", exception.retry_after + 1)
        return exception.retry_after + 1
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
                exc_info=True,
            )
            if (
                retry_state.attempt_number >= RETRY_MAX_TRIES - RETRY_PROXY_MAX_TRIES
                or not PROXY_SET
            ):
                PROXY["active"] = None
            else:
                proxy_url = PROXY_SET.pop()
                log.info("Using proxy: %s.", proxy_url)
                PROXY["active"] = proxy_url
            return RETRY_PROXY_MAX_TIMEOUT
        # connection errors
        return RETRY_MAX_TIMEOUT**retry_state.attempt_number
    log.warning(
        "Retrying request because of %s: %r.",
        exception.__class__.__name__,
        exception,
        exc_info=True,
    )
    # other errors
    return RETRY_MIN_TIMEOUT


def failed_request(retry_state: RetryCallState) -> None:
    """Returns None if request failed

    Args:
        retry_state (RetryCallState): retry state

    Returns:
        None
    """
    return


def retry_request(func, *, reraise=True):
    """Decorator that retries telegram send function

    Args:
        func (Callable): telegram send function
    """

    def wrapper(f):
        return AsyncRetrying(
            reraise=reraise,
            stop=stop_after_attempt(RETRY_MAX_TRIES),
            wait=wait_fixed_time,
            retry_error_callback=failed_request,
        ).wraps(f)

    return wrapper(func) if func else wrapper


@asynccontextmanager
async def get_async_client(with_proxy: bool = False):
    proxy_server = PROXY.get("active") if with_proxy else None
    try:
        async with httpx.AsyncClient(proxy=proxy_server) as client:
            yield client
    except Exception as exception:
        log.warning(
            "Failed to get an async httpx client, because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            with_proxy=with_proxy,
            proxy=proxy_server,
        )
        raise


@retry_request
async def make_request(
    url: str,
    method: str = "POST",
    headers: dict = None,
    follow_redirects: bool = True,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
    referer: str = None,
    xsrf: str = None,
    cookies: dict = None,
    proxy: bool = False,
    header_range: int = 0,
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
            request_headers = get_fake_headers()
        else:
            request_headers = headers.copy()
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
            request_headers[xsrf] = unquote(cookies["XSRF-TOKEN"])
        if header_range > 1:
            request_headers["Range"] = f"bytes=0-{header_range - 1}"

        return await client.request(
            method=method,
            url=url,
            headers=request_headers,
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
                request_headers = get_fake_headers()
            else:
                request_headers = headers.copy()
            # get cookies in session
            cookies = cookies if cookies else {}
            if referer and (new_cookies := await get_cookies(referer, headers=headers)):
                cookies.update(new_cookies)
            if xsrf:
                request_headers[xsrf] = unquote(cookies["XSRF-TOKEN"])

            async with client.stream(
                method=method,
                url=url,
                headers=request_headers,
                cookies=cookies if referer or cookies else None,
                follow_redirects=follow_redirects,
                timeout=timeout,
                **kwargs,
            ) as response:
                yield response
    except Exception as exception:
        log.warning(
            "Failed to stream an httpx respons, because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            url=url,
            method=method,
            headers=headers,
            follow_redirects=follow_redirects,
            timeout=timeout,
            referer=referer,
            xsrf=xsrf,
            cookies=cookies,
            proxy=proxy,
            kwargs=kwargs,
        )
        raise


@asynccontextmanager
async def get_content(url: str, chunk_size: int = 1024, **kwargs) -> AsyncIterator[bytes]:
    try:
        async with stream_response(url, **kwargs) as response:
            yield response.aiter_bytes(chunk_size)
    except Exception as exception:
        log.warning(
            "Failed to get content, because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            url=url,
            chunk_size=chunk_size,
            kwargs=kwargs,
        )
        raise


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
    try:
        async with get_content(url, **kwargs) as content_iterator:
            async for chunk in content_iterator:
                file.write(chunk)
        file.flush()
    except Exception as exception:
        log.warning(
            "Failed to write content, because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            url=url,
            file=file,
            kwargs=kwargs,
        )
        raise


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


async def get_body_length(url: str, chunk_size: int = 8192, **kwargs) -> int:
    length = 0
    async with stream_response(url, "GET", **kwargs) as response:
        async for chunk in response.aiter_bytes(chunk_size=chunk_size):
            length += len(chunk)
    return length


@cached(ttl=15, key_builder=lambda fn, *a, **kw: a[0])
async def get_content_headers(url: str, **kwargs) -> Optional[httpx.Headers]:
    # try HEAD request
    headers_with_head = await get_headers(url, method="HEAD", **kwargs)
    # try GET request, since HEAD may be forbidden
    headers_with_get = await get_headers(url, method="GET", **kwargs)
    # combine
    combined_headers = {}
    if headers_with_head is not None:
        combined_headers.update(headers_with_head)
    if headers_with_get is not None:
        for k, v in headers_with_get.items():
            if k not in combined_headers:
                combined_headers[k] = v
    return httpx.Headers(combined_headers)


@cached(ttl=15, key_builder=lambda fn, *a, **kw: a[0])
async def get_content_size(url: str, headers=get_fake_headers(), **kwargs) -> int:
    if file_headers := await get_content_headers(
        url,
        headers={**headers, "Access-Control-Expose-Headers": "Content-Length"},
        **kwargs,
    ):
        if size := int(file_headers.get("Content-Length", 0)):
            return size
    # just GET it
    return await get_body_length(url, **kwargs)


@cached(ttl=15, key_builder=lambda fn, *a, **kw: a[0])
async def get_content_name(
    url: str,
    pattern: re.Pattern,
    group: str = "name",
    **kwargs,
) -> str:
    file_name = ""
    if (matched := re.search(pattern, url)) and len(matched[group]) > 0:
        file_name = matched[group]
    elif (
        (file_headers := await get_content_headers(url, **kwargs))
        and (file_name := file_headers.get("Content-Disposition", ""))
        and (matched := re.search(pattern, file_name))
        and len(matched[group]) > 0
    ):
        file_name = matched[group]
    return re.sub(INVALID_CHARS, "", file_name)


@retry_request
async def get_content_type(url: str, mime=True, **kwargs) -> Optional[str]:
    async with get_content(url, **kwargs) as content_iterator:
        if chunk := await anext(content_iterator, None):
            return magic.from_buffer(chunk, mime=mime)
    log.warning("GetContentType: failed streaming file.", url=url, kwargs=kwargs)
    if response := await make_request(url, header_range=1024, **kwargs):
        if response.is_success and response.content:
            log.info(
                "GetContentType: got filewith length: %d.",
                len(response.content),
                url=url,
                kwargs=kwargs,
            )
            return magic.from_buffer(response.content, mime=mime)


@retry_request
async def get_content_extension(url: str, **kwargs) -> Optional[str]:
    kwargs["method"] = "HEAD"
    if mime_type := await get_content_type(url, mime=True, **kwargs):
        return mime_type.split("/")[-1]
    kwargs["method"] = "GET"
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
    if (
        (response := await make_request(url, method, **kwargs))
        and response.is_success
        and (file := response.content)
    ):
        return file
    else:
        raise Exception("No file content was received")

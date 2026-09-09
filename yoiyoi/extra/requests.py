"""Requests module"""

import re
import tempfile

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
from urllib.parse import unquote

# http requests
import httpx

# file extension
import magic

# structured logging
import structlog

# async caching
from aiocache import cached

# proxy manager
from yoiyoi.app.proxy import proxy_manager

# link types and other info
from yoiyoi.extra import DEFAULT_REQUEST_TIMEOUT, RETRY_PROXY_MAX_TRIES

# get fake headers and invlid chracters
from yoiyoi.extra.request_helpers import INVALID_CHARACTERS, get_fake_headers

# retry requests
from yoiyoi.extra.request_retriers import retry_request

# get logger
log = structlog.get_logger(__name__)


def _prepare_request_payload(
    url: str,
    headers: Optional[dict[str, Any]] = None,
    cookies: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepares and sanitizes headers and cookies for httpx requests."""
    request_headers = get_fake_headers() if not headers else headers.copy()
    request_cookies = cookies.copy() if cookies else {}

    if "headers" in request_headers and isinstance(request_headers["headers"], dict):
        log.debug("Unpacking nested 'headers' key found inside headers dict.", url=url)
        nested_headers = request_headers.pop("headers")
        request_headers.update(nested_headers)

    if "cookies" in request_headers and isinstance(request_headers["cookies"], dict):
        log.debug("Unpacking nested 'cookies' key found inside headers dict.", url=url)
        nested_cookies = request_headers.pop("cookies")
        request_cookies.update(nested_cookies)

    sanitized_headers = {}
    for key, val in request_headers.items():
        if isinstance(val, dict):
            log.warning(
                "Dropping invalid dictionary header value for key '%s': %r",
                key,
                val,
                url=url,
                invalid_key=key,
                invalid_val=val,
            )
            continue
        sanitized_headers[str(key)] = (
            str(val) if not isinstance(val, (str, bytes)) else val
        )

    return sanitized_headers, request_cookies


@asynccontextmanager
async def get_async_client(
    with_proxy: bool = False,
) -> AsyncGenerator[httpx.AsyncClient]:
    use_proxy = (
        with_proxy
        and proxy_manager.active
        and proxy_manager.request_attempts < RETRY_PROXY_MAX_TRIES
    )
    proxy_server = proxy_manager.active if use_proxy else None
    try:
        async with httpx.AsyncClient(proxy=proxy_server) as client:
            if proxy_server:
                proxy_manager.increment_attempt()
            yield client
        proxy_manager.reset_attempts()
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
    headers: Optional[dict[str, Any]] = None,
    follow_redirects: bool = True,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
    referer: Optional[str] = None,
    xsrf: Optional[str] = None,
    cookies: Optional[dict[str, Any]] = None,
    with_proxy: bool = False,
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
        with_proxy (bool, optional): use proxy for request. Defaults to False.

    Returns:
        httpx.Response: response
    """
    sanitized_headers, request_cookies = _prepare_request_payload(url, headers, cookies)
    use_proxy = (
        with_proxy
        and proxy_manager.active
        and proxy_manager.request_attempts < RETRY_PROXY_MAX_TRIES
    )
    proxy_server = proxy_manager.active if use_proxy else None

    try:
        async with httpx.AsyncClient(proxy=proxy_server) as client:
            if referer:
                try:
                    ref_resp = await client.get(
                        url=referer,
                        headers=sanitized_headers,
                        follow_redirects=True,
                    )
                    request_cookies.update(ref_resp.cookies)
                except Exception as ref_exc:
                    log.warning(
                        "Failed to fetch cookies from referer %s: %r",
                        referer,
                        ref_exc,
                        url=url,
                    )
            if xsrf and "XSRF-TOKEN" in request_cookies:
                sanitized_headers[xsrf] = unquote(request_cookies["XSRF-TOKEN"])
            if header_range > 1:
                sanitized_headers["Range"] = f"bytes=0-{header_range - 1}"

            return await client.request(
                method=method,
                url=url,
                headers=sanitized_headers,
                cookies=request_cookies if referer or request_cookies else None,
                follow_redirects=follow_redirects,
                timeout=timeout,
                **kwargs,
            )
    except Exception as exception:
        log.warning(
            "Failed to make request, because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            url=url,
            method=method,
            sanitized_headers=sanitized_headers,
            raw_headers_input=headers,
            request_cookies=request_cookies,
            follow_redirects=follow_redirects,
            timeout=timeout,
            referer=referer,
            xsrf=xsrf,
            proxy=with_proxy,
            header_range=header_range,
            kwargs=kwargs,
        )
        raise


@asynccontextmanager
async def stream_response(
    url: str,
    method: str = "POST",
    headers: Optional[dict[str, Any]] = None,
    follow_redirects: bool = True,
    timeout: int = 15,
    referer: Optional[str] = None,
    xsrf: Optional[str] = None,
    cookies: Optional[dict[str, Any]] = None,
    with_proxy: bool = False,
    **kwargs: Any,
) -> AsyncGenerator[httpx.Response]:
    """Makes request and streams response with httpx.AsyncClient

    Args:
        url (str): request url
        method (str, optional): request method. Defaults to "POST".
        headers (dict, optional): request headers. Defaults to None.
        follow_redirects (bool, optional): follow redirecting. Defaults to True.
        timeout (int, optional): request timeout. Defaults to 10.
        referer (str, optional): request referer to get cookies from. Defaults to None.
        xsrf (str, optional): extract xsrf token. Defaults to None.
        cookies (dict, optional): request cookies. Defaults to None.
        with_proxy (bool, optional): use proxy for request. Defaults to False.

    Returns:
        AsyncIterator[httpx.Response]: streaming response
    """
    sanitized_headers, request_cookies = _prepare_request_payload(url, headers, cookies)

    try:
        async with get_async_client(with_proxy=with_proxy) as client:
            # Get session cookies if referer is supplied
            if referer and (
                new_cookies := await get_cookies(referer, headers=sanitized_headers)
            ):
                request_cookies.update(new_cookies)

            if xsrf and "XSRF-TOKEN" in request_cookies:
                sanitized_headers[xsrf] = unquote(request_cookies["XSRF-TOKEN"])

            async with client.stream(
                method=method,
                url=url,
                headers=sanitized_headers,
                cookies=request_cookies if request_cookies else None,
                follow_redirects=follow_redirects,
                timeout=timeout,
                **kwargs,
            ) as response:
                yield response

    except Exception as exception:
        log.warning(
            "Failed to stream an httpx response due to %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # extra info
            url=url,
            method=method,
            sanitized_headers=sanitized_headers,
            raw_headers_input=headers,
            request_cookies=request_cookies,
            follow_redirects=follow_redirects,
            timeout=timeout,
            referer=referer,
            xsrf=xsrf,
            proxy=with_proxy,
            kwargs=kwargs,
        )
        raise


@asynccontextmanager
async def get_content(
    url: str,
    chunk_size: int = 1024,
    **kwargs: Any,
) -> AsyncGenerator[AsyncGenerator[bytes]]:
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
async def save_file(
    url: str,
    method: str = "GET",
    **kwargs: Any,
) -> Optional[str]:
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        await write_content_to_file(url, temp_file, method=method, **kwargs)
        return temp_file.name


@retry_request
async def write_content_to_file(
    url: str,
    file: tempfile.NamedTemporaryFile,
    **kwargs: Any,
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
async def get_headers(
    url: str,
    **kwargs: Any,
) -> Optional[httpx.Headers]:
    async with stream_response(url, **kwargs) as response:
        if response.is_success:
            return response.headers


@retry_request
async def get_cookies(
    url: str,
    **kwargs: Any,
) -> Optional[httpx.Cookies]:
    async with stream_response(url, "GET", **kwargs) as response:
        if response.is_success:
            return response.cookies


async def get_body_length(
    url: str,
    chunk_size: int = 8192,
    **kwargs: Any,
) -> int:
    length = 0
    async with stream_response(url, "GET", **kwargs) as response:
        async for chunk in response.aiter_bytes(chunk_size=chunk_size):
            length += len(chunk)
    return length


@cached(ttl=15, key_builder=lambda fn, *a, **kw: a[0])
async def get_content_headers(
    url: str,
    **kwargs: Any,
) -> Optional[httpx.Headers]:
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
async def get_content_size(
    url: str,
    headers: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> int:
    effective_headers = get_fake_headers() if headers is None else headers
    if file_headers := await get_content_headers(
        url,
        headers={**effective_headers, "Access-Control-Expose-Headers": "Content-Length"},
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
    **kwargs: Any,
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
    return re.sub(INVALID_CHARACTERS, "", file_name)


@retry_request
async def get_content_type(
    url: str,
    mime: bool = True,
    **kwargs: Any,
) -> Optional[str]:
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
async def get_content_extension(
    url: str,
    **kwargs: Any,
) -> Optional[str]:
    kwargs["method"] = "HEAD"
    if mime_type := await get_content_type(url, mime=True, **kwargs):
        return mime_type.split("/")[-1]
    kwargs["method"] = "GET"
    if mime_type := await get_content_type(url, mime=True, **kwargs):
        return mime_type.split("/")[-1]


async def get_file_info(
    url: str,
    size: bool = False,
    pattern: Optional[re.Pattern] = None,
    group: Optional[str] = None,
) -> dict[str, Any]:
    info = {}
    if size and (file_size := await get_content_size(url)):
        info["size"] = file_size
    if pattern and group and (file_name := await get_content_name(url, pattern, group)):
        info["name"] = file_name
    return info


@retry_request
async def get_file(
    url: str,
    method: str = "GET",
    **kwargs: Any,
) -> bytes:
    if (
        (response := await make_request(url, method, **kwargs))
        and response.is_success
        and (file := response.content)
    ):
        return file
    else:
        raise Exception("No file content was received")

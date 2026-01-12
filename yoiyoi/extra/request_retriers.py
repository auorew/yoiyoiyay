"""Retries module"""

import asyncio

# structured logging
import structlog

# httpx exceptions
from httpx import ConnectTimeout, ProxyError, ReadError, ReadTimeout, RemoteProtocolError

# telegram exceptions
from telegram.error import RetryAfter

# hardcore retrying
from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt

# get proxy
from yoiyoi.app.proxy import proxy_manager

# link types and other info
from yoiyoi.extra import RETRY_MAX_TIMEOUT, RETRY_MAX_TRIES, RETRY_MIN_TIMEOUT

# get logger
log = structlog.get_logger(__name__)


async def rotate_proxy_on_error(retry_state: RetryCallState):
    outcome = retry_state.outcome
    if outcome.failed:
        if isinstance(outcome.exception(), (ProxyError | ConnectTimeout | ReadError)):
            log.warning("Proxy error detected. Rotating...")
            await proxy_manager.rotate()


def sync_rotate_proxy(retry_state: RetryCallState):
    """Synchronous hook for tenacity."""
    outcome = retry_state.outcome
    if outcome.failed:
        exc = outcome.exception()
        # Only rotate on network/proxy-related errors
        if isinstance(exc, (ProxyError, ConnectTimeout, ReadError)):
            # Schedule rotation without blocking
            asyncio.create_task(proxy_manager.rotate())


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
        return RETRY_MAX_TIMEOUT
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
            before_sleep=rotate_proxy_on_error,
            retry_error_callback=failed_request,
        ).wraps(f)

    return wrapper(func) if func else wrapper

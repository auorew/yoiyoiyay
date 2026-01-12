"""Bot Jobs"""

import asyncio

# http requests
import httpx

# structured logging
import structlog

# telegram core bot api extension
from telegram.ext import ContextTypes

# get proxy
from yoiyoi.app.proxy import proxy_getter, proxy_manager

# get fake headers
from yoiyoi.extra.request_helpers import get_fake_headers

# settings
from yoiyoi.extra.settings import bot_settings

# setup logger
log = structlog.get_logger(__name__)


async def job_get_proxy(
    _: ContextTypes.DEFAULT_TYPE,
):
    """Get working proxy or nothing

    Args:
        _ (ContextTypes): callback context (not used)
    """
    if proxy_manager.is_static:
        log.debug("Proxy is static. Skipping getter job.")
        return
    proxy_set = await asyncio.to_thread(proxy_getter.get_sync_wrapper)
    proxy_manager.update_pool(proxy_set)
    if not proxy_manager.active:
        await proxy_manager.rotate()


async def job_health_checker(
    _: ContextTypes.DEFAULT_TYPE,
):
    """Ping the specified instance and log the result"""
    if not bot_settings.health_check_url:
        return

    try:
        hcu = str(bot_settings.health_check_url)
        async with httpx.AsyncClient(timeout=5) as client:
            if (response := await client.get(hcu, headers=get_fake_headers())).is_error:
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

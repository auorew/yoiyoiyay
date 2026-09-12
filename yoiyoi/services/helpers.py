from io import StringIO
from typing import Any, Dict, Optional

import msgspec
import structlog

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

# request helpers
from yoiyoi.extra.request_helpers import get_request_info

# requests
from yoiyoi.extra.requests import make_request

log = structlog.get_logger()


def decrypt_cookies(
    encrypted_cookies: Optional[str],
    secret_key: Optional[SecretStr],
) -> Optional[str]:
    """Decrypts base64/Fernet cookie string using a Pydantic SecretStr key."""
    if not encrypted_cookies or not secret_key:
        return None

    # Unwrap SecretStr value
    raw_key = secret_key.get_secret_value()
    if not raw_key:
        return None

    try:
        fernet = Fernet(raw_key.encode("utf-8") if isinstance(raw_key, str) else raw_key)
        return fernet.decrypt(encrypted_cookies.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        log.error("Failed to decrypt cookies: Invalid Fernet token or key mismatch.")
        return None
    except Exception as e:
        log.error("Error occurred while decrypting cookies.", error=str(e))
        return None


def get_yt_cookies(bot_settings: Any) -> Optional[str]:
    """Gets decrypted YouTube cookies as raw string."""
    return decrypt_cookies(bot_settings.yt_cookies, bot_settings.secret_key)


def get_tt_cookies(bot_settings: Any) -> Optional[str]:
    """Gets decrypted TikTok cookies as raw string."""
    return decrypt_cookies(bot_settings.tt_cookies, bot_settings.secret_key)


def get_yt_cookies_stream(bot_settings: Any) -> Optional[StringIO]:
    """Gets decrypted YouTube cookies wrapped in a StringIO stream."""
    cookies = get_yt_cookies(bot_settings)
    return StringIO(cookies) if cookies else None


def get_tt_cookies_stream(bot_settings: Any) -> Optional[StringIO]:
    """Gets decrypted TikTok cookies wrapped in a StringIO stream."""
    cookies = get_tt_cookies(bot_settings)
    return StringIO(cookies) if cookies else None


async def fetch_api_json(
    url: str,
    method: str = "POST",
    api_log: structlog.BoundLogger = log,
    retry_with: Optional[dict] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Executes HTTP request and parses JSON response using msgspec."""
    if not retry_with:
        response = await make_request(url=url, method=method, **kwargs)
    else:
        response = await make_request.retry_with(**retry_with)(
            url=url, method=method, **kwargs
        )

    if response is None:
        api_log.error(
            "No response object!",
            request={
                "method": method,
                "url": url,
                "headers": kwargs.get("headers", {}),
                "body": kwargs.get("data", None) or kwargs.get("json", None),
            },
        )
        return {}

    request_info = await get_request_info(response)

    if response.is_error:
        api_log.warning(
            "Request to API failed: %s.",
            response,
            status_code=response.status_code,
            response=response.content,
            request=request_info,
        )
        return {}

    try:
        info = msgspec.json.decode(response.content)
        api_log.debug("Loaded JSON.", json=info, request=request_info)
        return info
    except msgspec.DecodeError:
        api_log.warning(
            "Couldn't decode json response.",
            response=response.content,
            request=request_info,
        )
        return {}

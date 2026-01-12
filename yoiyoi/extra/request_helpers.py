"""Request helpers"""

import re

# structured logging
import structlog

# up-to-date user-agent
from fake_useragent import UserAgent

# get logger
log = structlog.get_logger(__name__)

# init user-agnet generator
ua_generator = UserAgent(browsers=["Chrome", "Edge", "Firefox"])

# static fake headers
FAKE_HEADERS = {
    "User-Agent": ua_generator.firefox,
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
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


# dynamic fake headers
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


# regex
INVALID_CHARACTERS = re.compile(r"[\/\\\?\%\*\:\|\"\<\>]")

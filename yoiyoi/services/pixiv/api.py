"""Pixiv API"""

from typing import Optional

# parse json
import msgspec

# structured logging
import structlog

# pixiv api
from pixivpy_async import AppPixivAPI, PixivClient

# request helpers
from yoiyoi.extra.request_helpers import PIXIV_HEADERS, get_fake_headers

# request retriers
from yoiyoi.extra.request_retriers import retry_request

# requests
from yoiyoi.extra.requests import get_content_size, make_request

# bot settings
from yoiyoi.extra.settings import bot_settings

# link types, link dictionary
from yoiyoi.services.constants import LINKS

# PixivMedia namedtuple
from yoiyoi.services.namedtuples import PixivContent, PixivMedia

# get logger
log = structlog.get_logger(__name__)


async def get_pixiv_media(illust: dict, get_sizes: bool = False) -> PixivMedia:
    """Collects information about pixiv artwork

    Args:
        illust (dict): dictionary of illustration.

    Returns:
        PixivMedia: artwork namedtuple.
    """
    illust_list = []
    if illust.type == "ugoira":
        if not (
            response := await make_request(
                "https://ugoira.com/api/illusts/queue",
                headers={**get_fake_headers(), "Content-Type": "application/json"},
                referer="https://ugoira.com/",
                data=msgspec.json.encode({"text": str(illust.id)}),
            )
        ):
            return
        try:
            if not (ugoira := msgspec.json.decode(response.content))["ok"]:
                return
        except msgspec.DecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        else:
            illust_list.append(
                (
                    str(illust.id),
                    ugoira["data"][0]["preview"]["mp4"],
                    illust.image_urls.large,
                )
            )
    elif illust.meta_single_page:
        # only one illustration
        illust_list.append(
            (
                f"{illust.id}_p0",
                illust.meta_single_page.original_image_url,
                illust.image_urls.large,
            )
        )
    elif illust.type not in ("ugoira", "novel"):
        for page in illust.meta_pages:
            illust_list.append(
                (
                    page.image_urls.original.rsplit("/", 1)[1].split(".")[0],
                    page.image_urls.original,
                    page.image_urls.large,
                )
            )
    content = []
    for illust_info in illust_list:
        if get_sizes:
            original_size = await get_content_size(illust_info[1], PIXIV_HEADERS)
            thumb_size = await get_content_size(illust_info[2], PIXIV_HEADERS)
        else:
            original_size, thumb_size = 0, 0
        content.append(
            PixivContent(
                illust_info[0],
                illust_info[1],
                original_size,
                illust_info[2],
                thumb_size,
            )
        )
    return PixivMedia(
        LINKS["pixiv"]["link"].format(id=illust.id),
        illust.id,
        illust.type,  # 'ugoira' 'illust' 'manga' 'novel'
        illust.user.id,
        illust.user.name,
        illust.user.account,
        illust.create_date,
        illust.title,
        illust.caption,
        content,
    )


@retry_request
async def get_pixiv_info(pixiv_id: int) -> PixivMedia:
    """Gets illustration info with pixiv API by illustration id

    Args:
        pixiv_id (int): pixiv illustration id.

    Returns:
        PixivMedia: artwork namedtuple.
    """
    async with PixivClient() as client:
        aapi = AppPixivAPI(client=client)
        await aapi.login(refresh_token=bot_settings.px_refresh)
        # Doing stuff...
        log.debug("Trying to fetch artwork...")
        json_result = await aapi.illust_detail(pixiv_id)
        if json_result.error:
            log.error("This artwork was probably deleted.")
            return
        if not json_result.illust.visible:
            log.error("This artwork is not public.")
            return
        log.debug("Response: %r.", json_result.illust)
        return json_result.illust


async def get_pixiv_links(pixiv_id: int) -> Optional[PixivMedia]:
    """Gets pixiv illustration info with pixiv API by illustration id

    Args:
        pixiv_id (int): pixiv illustration id.

    Returns:
        Optional[PixivMedia]: artwork namedtuple.
    """
    if info := await get_pixiv_info(pixiv_id):
        return await get_pixiv_media(info)
    return

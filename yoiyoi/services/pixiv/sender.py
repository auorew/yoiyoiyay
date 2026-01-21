"""Pixiv sender"""

import structlog

# bot constants
from yoiyoi.bot import PixivParse

# bot formatters
from yoiyoi.bot.formatters import get_video_info, make_thumb_name, pixiv_parse

# get info
from yoiyoi.bot.helpers import get_info

# request headers
from yoiyoi.extra.request_helpers import PIXIV_HEADERS, get_fake_headers

# media styles
from yoiyoi.extra.styles import PixivStyle

# file utils
from yoiyoi.extra.utils import move_file

# base sender class and media item dataclass
from yoiyoi.services.base import BaseSender, MediaItem, SenderError

# media tuples
from yoiyoi.services.namedtuples import PixivContent

# pixiv api and types
from yoiyoi.services.pixiv.api import get_pixiv_links

# setup logger
log = structlog.get_logger(__name__)


class PixivSender(BaseSender):
    SERVICE = "pixiv"

    async def get_media_generator(self):
        self.log.info("Pixiv Link: %s.", self.link.link)

        if not (art := await get_pixiv_links(self.link.id)):
            raise SenderError(
                message=(
                    "can't be found or downloaded! "
                    "If this seems to be wrong, try again later."
                ),
                telegram_message=(
                    "can't be found or downloaded\\! "
                    "If this seems to be wrong, try again later\\."
                ),
            )

        info = await get_info(self.link, PixivStyle, self.chat, art)
        count = len(art.content)
        if art.type == "ugoira":
            item = art.content[0]
            # Ugoira requires specific referer headers for the original zip
            headers = {
                **get_fake_headers(),
                "Range": "bytes=0-",
                "Referer": "https://t-hk.ugoira.com/",
            }

            procpath, filepath = await self.download_helper(item.original, headers)
            if not procpath:
                raise SenderError(
                    message=(
                        "can't be downloaded! The bot failed to download the content."
                    ),
                    telegram_message=(
                        "can't be downloaded\\! The bot failed to download the content\\."
                    ),
                )

            videoinfo = await get_video_info(procpath)
            if not all(videoinfo):
                raise SenderError(
                    message=(
                        "can't be uploaded! "
                        "Corrupted video stream. "
                        "If this seems to be wrong, try again later."
                    ),
                    telegram_message=(
                        "can't be uploaded\\! "
                        "Corrupted video stream\\. "
                        "If this seems to be wrong, try again later\\."
                    ),
                )

            # get PixivContent.thumb
            thumbfile, _ = await self.download_helper(item.thumb, headers=PIXIV_HEADERS)
            thumbname = await make_thumb_name(filepath.name, thumbfile)
            thumbpath = move_file(thumbfile, self.storage_dir / thumbname)
            self.storage.add(thumbpath)

            yield MediaItem(
                path=procpath,
                type="video",
                caption=info,
                thumb_path=thumbpath,
                width=videoinfo[0],
                height=videoinfo[1],
                duration=videoinfo[2],
            )

        else:
            ids = tuple(range(1, count + 1))
            if count > 1:
                status, parsed_ids = await pixiv_parse(self.link.illust, count)
                match status:
                    case PixivParse.SUCCESS:
                        ids = parsed_ids
                    case PixivParse.OUT_OF_RANGE:
                        raise SenderError(
                            message=(
                                "can't be sent, because the bot "
                                "can't send more than 10 files!"
                            ),
                            telegram_message=(
                                "can't be sent, because the bot "
                                "*can't* send more than 10 files\\!"
                            ),
                        )
                    case PixivParse.NOT_WITHIN_RANGE:
                        raise SenderError(
                            message=(
                                "can't be sent, because the numbers "
                                f"are not within range: [1-{count}]!"
                            ),
                            telegram_message=(
                                "can't be sent, because the numbers "
                                "are *not within* range: "
                                f"\\[`1`\\-`{count}`\\]\\!"
                            ),
                        )
                    case PixivParse.NO_INFO:
                        raise SenderError(
                            message=(
                                "can't be sent, because the bot requires "
                                "the order of illustrations to be specified "
                                "with [link] + [ids] syntax! "
                                "See */help* for more info.\n\n"
                                f"Choose illustrations in range: [1-{count}]."
                            ),
                            telegram_message=(
                                "can't be sent, because the bot requires "
                                "the order of illustrations to be specified "
                                "with \\[`link`\\] `+` \\[`ids`\\] syntax\\! "
                                "See */help* for more info\\.\n\n"
                                "Choose illustrations in range: "
                                f"\\[`1`\\-`{count}`\\]\\."
                            ),
                        )
                    case _:
                        raise SenderError(
                            message=(
                                "can't be sent, because something went wrong "
                                "while parsing your input."
                            ),
                            telegram_message=(
                                "can't be sent, because something went wrong "
                                "while parsing your input\\."
                            ),
                        )

            for i, idx in enumerate(ids):
                item: PixivContent = art.content[idx - 1]

                procpath, filepath = await self.download_helper(
                    item.original,
                    PIXIV_HEADERS,
                )
                if not procpath:
                    raise SenderError(
                        message=(
                            "can't be downloaded! "
                            "The bot failed to download the content."
                        ),
                        telegram_message=(
                            "can't be downloaded\\! "
                            "The bot failed to download the content\\."
                        ),
                    )

                yield MediaItem(
                    path=procpath,
                    type="photo",
                    caption=info,
                    orig_path=filepath if self.chat.px_orig else None,
                )

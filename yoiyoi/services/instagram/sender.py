"""Instagram sender"""

import structlog

# bot formatters
from yoiyoi.bot.formatters import get_video_info, make_thumb_name

# file utils
from yoiyoi.extra.utils import move_file

# base sender class and media item dataclass
from yoiyoi.services.base import BaseSender, MediaItem, SenderError

# instagram api
from yoiyoi.services.instagram.api import get_instagram_links

# setup logger
log = structlog.get_logger(__name__)


class InstagramSender(BaseSender):
    SERVICE = "instagram"

    async def get_media_generator(self):
        self.log.info("Instagram Link: %s.", self.link.link)

        if not (media := await get_instagram_links(self.link.link)):
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

        info = media[0].source if self.chat.include_link else None

        # Headers required for Instagram requests
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;"
            "q=0.8,application/signed-exchange;v=b3;"
            "q=0.7",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Dnt": "1",
            "Priority": "u=0, i",
            "Sec-Ch-Ua": '"Chromium";"'
            '"v="124", "Google Chrome";"'
            '"v="124", "Not-A.Brand";"'
            '"v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": "macOS",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        for item in media:
            if item.type == "image":
                procpath, filepath = await self.download_helper(
                    item.link,
                    headers=headers,
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
                    orig_path=filepath if self.chat.in_orig else None,
                )
            else:
                procpath, filepath = await self.download_helper(
                    item.link,
                    headers=headers,
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

                # get InstaMedia.thumb
                thumbfile, _ = await self.download_helper(item.thumb)
                thumbname = await make_thumb_name(filepath.name, thumbfile)
                thumbpath = move_file(thumbfile, self.storage_dir / thumbname)
                self.storage.add(thumbpath)

                yield MediaItem(
                    path=filepath,
                    type="video",
                    caption=info,
                    thumb_path=thumbpath,
                    width=videoinfo[0],
                    height=videoinfo[1],
                    duration=videoinfo[2],
                )

"""Discord sender"""

import structlog

# bot formatters
from yoiyoi.bot.formatters import get_video_info, make_thumb_name

# process video to create thumbnail
from yoiyoi.bot.processors import create_thumbnail

# http requests
from yoiyoi.extra.requests import get_content_type

# file utils
from yoiyoi.extra.utils import move_file

# base sender class and media item dataclass
from yoiyoi.services.base import BaseSender, MediaItem, SenderError

# setup logger
log = structlog.get_logger(__name__)


class DiscordSender(BaseSender):
    SERVICE = "discord"

    async def get_media_generator(self):
        self.log.info("Discord Link: %s.", self.link.link)

        content_type = await get_content_type(self.link.link, method="GET")

        if content_type == "text/plain":
            raise SenderError(
                message="can't be found or downloaded, because it's no longer available.",
                telegram_message=(
                    "can't be found or downloaded, because it\\'s no longer available\\."
                ),
            )

        info = self.link.link if self.chat.include_link else None

        procpath, filepath = await self.download_helper(self.link.link)

        if not procpath:
            raise SenderError(
                message="can't be downloaded! The bot failed to download the content.",
                telegram_message=(
                    "can't be downloaded\\! The bot failed to download the content\\."
                ),
            )

        if content_type.split("/")[0] == "video":
            video_info = await get_video_info(procpath)
            if not all(video_info[:3]):
                raise SenderError(
                    message=(
                        "can't be uploaded! "
                        "Corrupted video stream. "
                        "If this seems to be wrong, try again later."
                    ),
                    telegram_message=(
                        "can't be uploaded\\! "
                        "Corrupted video stream\\\\. "
                        "If this seems to be wrong, try again later\\."
                    ),
                )

            # create thumbnail
            thumbfile = await create_thumbnail(procpath)
            thumbname = await make_thumb_name(filepath.name, thumbfile)
            thumbpath = move_file(thumbfile, self.storage_dir / thumbname)
            self.storage.add(thumbpath)

            yield MediaItem(
                path=procpath,
                type="video",
                caption=info,
                thumb_path=thumbpath,
                width=video_info[0],
                height=video_info[1],
                duration=video_info[2],
                orig_path=filepath,
            )

        else:
            yield MediaItem(
                path=procpath,
                type="photo",
                caption=info,
                orig_path=filepath,
            )

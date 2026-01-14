"""TikTok sender"""

import structlog

# bot formatters
from yoiyoi.bot.formatters import get_video_info, make_thumb_name

# get info
from yoiyoi.bot.helpers import get_info

# http requests
from yoiyoi.extra.requests import save_file

# media styles
from yoiyoi.extra.styles import TikTokStyle

# file utils
from yoiyoi.extra.utils import move_file

# base sender class and media item dataclass
from yoiyoi.services.base import BaseSender, MediaItem, SenderError

# media kind
from yoiyoi.services.constants import TikTokMediaKind

# media tuples
from yoiyoi.services.namedtuples import TikTokPhoto, TikTokVideo

# tiktok api
from yoiyoi.services.tiktok.api import get_tiktok_links

# setup logger
log = structlog.get_logger(__name__)


class TikTokSender(BaseSender):
    SERVICE = "tiktok"

    async def get_media_generator(self):
        self.log.info("TikTok Link: %s.", self.link.link)

        if not (media := await get_tiktok_links(self.link.link)):
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

        info = await get_info(self.link, TikTokStyle, self.chat, media)
        if media.kind == TikTokMediaKind.SLIDESHOW and self.chat.tt_slide_mode == 1:
            photos = [x for x in media.content if isinstance(x, TikTokPhoto)]
            for media_photo in photos:
                imagepath, filepath = await self.download_helper(media_photo.link)
                if not imagepath:
                    raise SenderError(
                        message=(
                            "can't be downloaded! "
                            "If this seems to be wrong, try again later."
                        ),
                        telegram_message=(
                            "can't be downloaded\\! "
                            "If this seems to be wrong, try again later\\."
                        ),
                    )

                yield MediaItem(
                    path=imagepath,
                    type="photo",
                    caption=info,
                    orig_path=filepath if self.chat.tt_orig else None,
                )

        else:
            videos = [x for x in media.content if isinstance(x, TikTokVideo)]
            target_video = next((v for v in videos if 0 < v.size < 50 << 20), None)
            if target_video:
                videopath, filepath = await self.download_helper(
                    target_video.link, headers=target_video.extra
                )
                if not videopath:
                    raise SenderError(
                        message=(
                            "can't be downloaded! "
                            "If this seems to be wrong, try again later."
                        ),
                        telegram_message=(
                            "can't be downloaded\\! "
                            "If this seems to be wrong, try again later\\."
                        ),
                    )

                video_info = await get_video_info(filepath)
                if not all(video_info):
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

                thumbfile = await save_file(media.thumb)
                thumbname = await make_thumb_name(filepath.name, thumbfile)
                thumbpath = move_file(thumbfile, self.storage_dir / thumbname)
                self.storage.add(thumbpath)

                yield MediaItem(
                    path=filepath,
                    type="video",
                    caption=info,
                    thumb_path=thumbpath,
                    width=video_info[0],
                    height=video_info[1],
                    duration=video_info[2],
                )

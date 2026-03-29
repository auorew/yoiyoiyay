"""YouTube Short sender"""

import structlog

# bot constants
from yoiyoi.bot import MAX_VIDEO_SIZE

# bot formatters
from yoiyoi.bot.formatters import get_video_info, make_thumb_name

# get info
from yoiyoi.bot.helpers import get_info

# bot processors
from yoiyoi.bot.processors import crop_shorts_thumbnail

# media styles
from yoiyoi.extra.styles import YouTubeShortStyle

# file utils
from yoiyoi.extra.utils import move_file

# base sender class and media item dataclass
from yoiyoi.services.base import BaseSender, MediaItem, SenderError

# media tuples
from yoiyoi.services.namedtuples import YouTubeShortContent

# youtube short api
from yoiyoi.services.youtube_short.api import get_youtube_short_links

# setup logger
log = structlog.get_logger(__name__)


class YouTubeShortSender(BaseSender):
    SERVICE = "youtube_short"

    async def get_media_generator(self):
        self.log.info("YouTube Short Link: %s.", self.link.link)

        if not (media := await get_youtube_short_links(self.link)):
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

        info = await get_info(self.link, YouTubeShortStyle, self.chat, media)
        videos = [x for x in media.content if isinstance(x, YouTubeShortContent)]
        target_video: YouTubeShortContent = next(
            (v for v in videos if 0 < v.size < MAX_VIDEO_SIZE), None
        )
        if target_video:
            videopath, filepath = await self.download_helper(
                target_video.link,
                headers=target_video.headers,
                **target_video.kwargs,
            )
            if not (videopath and videopath.exists()):
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

            video_info = await get_video_info(videopath)
            if not all(video_info[:3]):
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

            # get YouTubeShortMedia.thumb
            thumbfile, _ = await self.download_helper(media.thumb)
            thumbname = await make_thumb_name(filepath.name, thumbfile)
            thumbpath = move_file(thumbfile, self.storage_dir / thumbname)
            await crop_shorts_thumbnail(thumbpath)
            self.storage.add(thumbpath)

            yield MediaItem(
                path=videopath,
                type="video",
                caption=info,
                thumb_path=thumbpath,
                width=video_info[0],
                height=video_info[1],
                duration=video_info[2],
            )

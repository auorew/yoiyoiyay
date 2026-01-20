"""Xiaohongshu sender"""

import structlog

# bot constants
from yoiyoi.bot import MAX_VIDEO_SIZE

# bot formatters
from yoiyoi.bot.formatters import get_video_info, make_thumb_name

# get info
from yoiyoi.bot.helpers import get_info

# http requests
from yoiyoi.extra.requests import save_file

# media styles
from yoiyoi.extra.styles import XiaohongshuStyle

# file utils
from yoiyoi.extra.utils import move_file

# base sender class and media item dataclass
from yoiyoi.services.base import BaseSender, MediaItem, SenderError

# media tuples
from yoiyoi.services.namedtuples import XiaohongshuVideo

# xiaohongshu api
from yoiyoi.services.xiaohongshu.api import get_xiaohongshu_links

# setup logger
log = structlog.get_logger(__name__)


class XiaohongshuSender(BaseSender):
    SERVICE = "xiaohongshu"

    async def get_media_generator(self):
        self.log.info("Xiaohongshu Link: %s.", self.link.link)

        if not (media := await get_xiaohongshu_links(self.link.link)):
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

        info = await get_info(self.link, XiaohongshuStyle, self.chat, media)
        videos = [x for x in media.content if isinstance(x, XiaohongshuVideo)]

        if not videos:
            raise SenderError(
                message="can't be sent, because didn't find any video!",
                telegram_message="can't be sent, because didn't find any video\\!",
            )

        target_video = next(
            (v for v in videos if 0 < v.size < MAX_VIDEO_SIZE),
            None,
        )

        if not target_video:
            self.log.error("Video file is too big.")
            raise SenderError(
                message="can't be sent, because video file is too big!",
                telegram_message="can't be sent, because video file is too big\\!",
            )

        videopath, filepath = await self.download_helper(
            target_video.link,
        )

        if not videopath:
            raise SenderError(
                message=(
                    "can't be downloaded! " "If this seems to be wrong, try again later."
                ),
                telegram_message=(
                    "can't be downloaded\\! "
                    "If this seems to be wrong, try again later\\."
                ),
            )

        video_info = await get_video_info(videopath)
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
            path=videopath,
            type="video",
            caption=info,
            thumb_path=thumbpath,
            width=video_info[0],
            height=video_info[1],
            duration=video_info[2],
        )

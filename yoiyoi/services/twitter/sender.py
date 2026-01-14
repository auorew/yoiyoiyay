"""Twitter sender"""

from typing import Optional

import structlog

# bot constants
from yoiyoi.bot import MAX_VIDEO_DURATION, MAX_VIDEO_SIZE, PixivParse

# bot formatters
from yoiyoi.bot.formatters import esc, get_video_info, make_thumb_name, pixiv_parse

# get info
from yoiyoi.bot.helpers import get_info

# bot senders
from yoiyoi.bot.senders import send_error, send_reply

# http requests
from yoiyoi.extra.requests import save_file

# media styles
from yoiyoi.extra.styles import TwitterStyle

# file utils
from yoiyoi.extra.utils import move_file

# base sender class and media item dataclass
from yoiyoi.services.base import BaseSender, MediaItem, SenderError

# media tuples
from yoiyoi.services.namedtuples import TweetContent

# twitter api
from yoiyoi.services.twitter.api import get_twitter_links

# setup logger
log = structlog.get_logger(__name__)


class TwitterSender(BaseSender):
    SERVICE = "twitter"

    async def get_media_generator(self):
        self.log.info("Twitter Link: %s.", self.link.link)

        if not (tweet := await get_twitter_links(self.link.id)):
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

        info = await get_info(self.link, TwitterStyle, self.chat, tweet)
        count = len(tweet.content)
        ids = tuple(range(1, count + 1))
        if self.link.illust:
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
            media: TweetContent = tweet.content[idx - 1]
            procpath, filepath = await self.download_helper(media.links[0])

            if media.type == "photo":
                yield MediaItem(
                    path=procpath,
                    type="photo",
                    caption=info,
                    orig_path=filepath if self.chat.tw_orig else None,
                )
            else:
                video_info = await get_video_info(procpath)
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

    async def _choose_twitter_video(self, content: TweetContent) -> Optional[str]:
        """Chooses a suitable video link or sends download links if too large."""
        if content.duration > MAX_VIDEO_DURATION:
            video_links = ", ".join(
                [f"[\\[*{i}*\\]]({link})" for i, link in enumerate(content.links, 1)]
            )
            await send_error(
                self.update,
                f"Sorry, video is *too long*\\: `{esc(str(content.duration))} s`\\! ",
            )
            await send_reply(
                self.update, f"Here's your download links\\: {video_links}\\."
            )
            return None

        for link, size in zip(content.links, content.sizes, strict=False):
            if size > MAX_VIDEO_SIZE:
                await send_error(self.update, "Sorry, file is *too huge*\\!")
                await send_reply(self.update, f"[Download link]({link})\\.")
                await send_reply(self.update, "Trying to get smaller version\\.\\.\\.")
                continue
            return link
        return None

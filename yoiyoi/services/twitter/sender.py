"""Twitter sender"""

from typing import Optional

import structlog

# bot constants
from yoiyoi.bot import MAX_VIDEO_DURATION, MAX_VIDEO_SIZE, PixivParse

# bot formatters
from yoiyoi.bot.formatters import esc, get_video_info, pixiv_parse

# get info
from yoiyoi.bot.helpers import get_info

# bot processors
from yoiyoi.bot.processors import process_image, stitch_images

# bot senders
from yoiyoi.bot.senders import send_error, send_reply

# media styles
from yoiyoi.extra.styles import TwitterStyle

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

        # handle stitching if requested and multiple photos are selected
        stitch_action = self.link.action.get("stitch") if self.link.action else None
        photo_indices = [idx for idx in ids if tweet.content[idx - 1].type == "photo"]
        if stitch_action and len(photo_indices) >= 2:
            self.log.info(
                "Stitching requested for Twitter link %s: "
                "%d photos selected (out of %d total media)",
                self.link.id,
                len(photo_indices),
                len(tweet.content),
                tweet_id=self.link.id,
                photo_count=len(photo_indices),
                total_media=len(tweet.content),
                action=stitch_action,
            )
            downloaded_paths = []
            for idx in photo_indices:
                item: TweetContent = tweet.content[idx - 1]
                _, filepath = await self.download_helper(item.links[0])
                if not filepath or not filepath.exists():
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
                downloaded_paths.append(filepath)

            stitched_filename = f"stitched_{self.link.id}.png"
            stitched_raw_path = self.storage_dir / stitched_filename

            # Extract configuration safely from stitch_action dictionary
            if isinstance(stitch_action, dict):
                fill_color = stitch_action.get("fill")
                gap = stitch_action.get("gap")
                border_radius = stitch_action.get("radius")
                frame_margins = stitch_action.get("margin")
            else:
                # Fallback if stitch_action happens to be a direct string or simple value
                fill_color = stitch_action if isinstance(stitch_action, str) else None
                gap = border_radius = frame_margins = None

            self.log.info(
                "Calling stitch_images: "
                "fill_color=%r, gap=%r, radius=%r, margins=%r, output=%s",
                fill_color,
                gap,
                border_radius,
                frame_margins,
                stitched_raw_path.name,
                fill_color=fill_color,
                gap=gap,
                border_radius=border_radius,
                frame_margins=frame_margins,
                output=stitched_raw_path.name,
                tweet_id=self.link.id,
            )

            await stitch_images(
                image_paths=downloaded_paths,
                output_path=stitched_raw_path,
                fill_color=fill_color,
                border_radius=border_radius,
                gap=gap,
                frame_margins=frame_margins,
            )
            self.storage.add(stitched_raw_path)

            procpath = await process_image(stitched_raw_path)
            if procpath and procpath != stitched_raw_path:
                self.log.info(
                    "Downscaled stitched image for Telegram: %s",
                    procpath.name,
                    downscaled_file=procpath.name,
                    tweet_id=self.link.id,
                )
                self.storage.add(procpath)
            else:
                procpath = stitched_raw_path

            yield MediaItem(
                path=procpath,
                type="photo",
                caption=info,
                orig_path=stitched_raw_path if self.chat.tw_orig else None,
            )
            return
        elif stitch_action:
            self.log.warning(
                "Stitch action was requested but could not proceed "
                "(photo_indices count=%d)",
                len(photo_indices),
                tweet_id=self.link.id,
                photo_count=len(photo_indices),
                action=stitch_action,
            )

        for i, idx in enumerate(ids):
            item: TweetContent = tweet.content[idx - 1]

            if item.type == "photo":
                procpath, filepath = await self.download_helper(item.links[0])
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
                    orig_path=filepath if self.chat.tw_orig else None,
                )
            else:
                if not (videolink := await self._choose_twitter_video(item)):
                    self.log.info("Skipping downloading video...")
                    raise SenderError(
                        message=("can't be sent, video is too huge!"),
                        telegram_message=("can't be sent, video is too huge\\!"),
                    )

                procpath, filepath = await self.download_helper(videolink)
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
                            "Corrupted video stream\\. "
                            "If this seems to be wrong, try again later\\."
                        ),
                    )

                thumbpath = await self.prepare_thumbnail(
                    thumb=item.thumb,
                    videopath=procpath,
                    video_width=video_info[0],
                    video_height=video_info[1],
                )

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

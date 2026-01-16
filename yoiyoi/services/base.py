"""Base module for services"""

import asyncio
import gc

from abc import ABC, abstractmethod
from contextlib import ExitStack
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Optional

# structured logging
import structlog

# decrypting
from cryptography.fernet import Fernet

# telegram core bot api
from telegram import (
    InputFile,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Update,
)

# telegram constants
from telegram.constants import MediaGroupLimit as MGL
from telegram.constants import ParseMode as PM

# yt-dlp
from yt_dlp import YoutubeDL

# bot constants and cache dir
from yoiyoi.bot import CACHE_DIR, MAX_REQUEST_SIZE, MAX_VIDEO_SIZE

# bot formatters
from yoiyoi.bot.formatters import esc, make_file_name

# bot processors
from yoiyoi.bot.processors import process_image, process_video

# bot senders
from yoiyoi.bot.senders import reply_media_group, send_error

# database table
from yoiyoi.db.models import Chat

# http requests
from yoiyoi.extra.requests import save_file

# settings
from yoiyoi.extra.settings import bot_settings

# file utils
from yoiyoi.extra.utils import delete_files, move_file

# Link namedtuple
from yoiyoi.services.namedtuples import Link

# setup logger
log = structlog.get_logger(__name__)

ydl_opts_base = {
    "extractor_args": {
        "youtube": {
            "player_client": ["mweb"],
            "skip": ["web"],
            "youtubepot-bgutilhttp:base_url": "http://127.0.0.1:4416",
        }
    },
    "format": (
        f"bestvideo[ext=mp4][vcodec^=avc1][filesize_approx<{MAX_VIDEO_SIZE}]+"
        f"bestaudio[ext=m4a]/best[ext=mp4][filesize_approx<{MAX_VIDEO_SIZE}]"
    ),
    # convert to mp4
    # "merge_output_format": "mp4",
    # "postprocessors": [
    #     {
    #         "key": "FFmpegVideoRemuxer",
    #         "preferedformat": "mp4",
    #     }
    # ],
    # memory limiting
    "buffersize": 1024 * 16,
    "max_filesize": MAX_VIDEO_SIZE,
    # remove metadata
    "writethumbnail": False,
    "write_all_thumbnails": False,
    "addmetadata": False,
    "writeinfojson": False,
    "noplaylist": True,
    # additional
    "extract_flat": "in_playlist",
    "check_formats": None,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "no_color": True,
    "ignore_no_formats_error": True,
    # other settings
    "quiet": True,
    "nocheckcertificate": True,
    "js_runtimes": {"deno": {}},
    "remote_components": ["ejs:github"],
}


@dataclass
class MediaItem:
    path: Path
    type: str  # 'video', 'photo'
    caption: str = ""
    thumb_path: Optional[Path] = None
    orig_path: Optional[Path] = None
    width: int = 0
    height: int = 0
    duration: int = 0


class SenderError(Exception):
    def __init__(self, message: str, telegram_message: str):
        super().__init__(message)
        self.message = message
        self.telegram_message = telegram_message


class BaseSender(ABC):
    SERVICE: str = ""

    def __init__(self, update: Update, link: Link, chat: Chat):
        if self.SERVICE is None or self.SERVICE == "":
            raise NotImplementedError(
                f"Class {self.__class__.__name__} must define a 'SERVICE' attribute."
            )

        self.update: Update = update
        self.link: Link = link
        self.chat: Chat = chat
        self.update_id: int = update.update_id

        # setup storage
        self.storage_dir: Path = Path(CACHE_DIR / str(self.update_id))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage: set = set()

        # error message
        self.error: str = f"This {self.SERVICE} content({self.link.link})"
        self.telegram_error: str = (
            f"[*This {esc(self.SERVICE)} content*]({self.link.link})"
        )

        # sender logger
        self.log: structlog.BoundLogger = log.bind(service=self.SERVICE)

    @abstractmethod
    async def get_media_generator(self):
        """Yields MediaItem objects one by one."""
        pass

    async def run(self):
        """Main entry point."""
        try:
            generator = self.get_media_generator()
            await self._send_batched(generator)

        except SenderError as error:
            self.log.error(
                "SenderError in %s: %r.",
                self.__class__.__name__,
                error.message,
                # more info
                chat=self.chat,
                storage=self.storage,
            )
            await send_error(
                self.update,
                f"{self.telegram_error} {error.telegram_message}",
                do_quote=not self.chat.delete_link,
            )

        except Exception as exception:
            self.log.error(
                "Error in %s: %r.",
                self.__class__.__name__,
                exception,
                exc_info=True,
                # more info
                chat=self.chat,
                storage=self.storage,
            )
            await send_error(
                self.update,
                f"{self.telegram_error} crashed the bot unexpectedly\\.",
                do_quote=not self.chat.delete_link,
            )
        finally:
            self._cleanup()

    async def _send_batched(self, generator):
        """Processes items in chunks with automatic memory flushing."""
        batch_items = []
        current_media_size = 0
        current_doc_size = 0

        async for item in generator:
            # get sizes
            item_media_size = item.path.stat().st_size
            item_doc_size = item.orig_path.stat().st_size if item.orig_path else 0

            # if reached any limit then flush
            if (
                (len(batch_items) >= MGL.MAX_MEDIA_LENGTH)
                or ((current_media_size + item_media_size) > MAX_REQUEST_SIZE)
                or ((current_doc_size + item_doc_size) > MAX_REQUEST_SIZE)
            ):
                if batch_items:
                    await self._process_and_flush(batch_items)
                    batch_items.clear()
                    current_media_size = 0
                    current_doc_size = 0

            # add otherwise
            batch_items.append(item)
            # accumulate sizes
            current_media_size += item_media_size
            current_doc_size += item_doc_size

        if batch_items:
            await self._process_and_flush(batch_items)

    async def _process_and_flush(self, items):
        """Opens files, sends to Telegram, and closes everything immediately."""
        with ExitStack() as stack:
            media_group = []
            doc_group = []

            for idx, item in enumerate(items):
                media_handle = stack.enter_context(item.path.open("rb"))
                input_media = InputFile(
                    media_handle,
                    filename=item.path.name,
                    attach=True,
                    read_file_handle=False,
                )

                thumb_handle = input_thumb = None
                if item.thumb_path:
                    thumb_handle = stack.enter_context(item.thumb_path.open("rb"))
                    input_thumb = InputFile(
                        thumb_handle,
                        filename=item.path.name,
                        attach=True,
                        read_file_handle=False,
                    )

                caption = item.caption if idx == 0 else None

                # Build Telegram objects
                if item.type == "video":
                    media_group.append(
                        InputMediaVideo(
                            media=input_media,
                            thumbnail=input_thumb,
                            caption=caption,
                            parse_mode=PM.HTML,
                            width=item.width,
                            height=item.height,
                            duration=item.duration,
                        )
                    )
                else:
                    media_group.append(
                        InputMediaPhoto(
                            media=input_media,
                            caption=caption,
                            parse_mode=PM.HTML,
                        )
                    )

                if item.orig_path:
                    doc_handle = stack.enter_context(item.orig_path.open("rb"))
                    input_doc = InputFile(
                        doc_handle,
                        filename=item.orig_path.name,
                        attach=True,
                        read_file_handle=False,
                    )
                    doc_group.append(
                        InputMediaDocument(
                            media=input_doc,
                            thumbnail=input_thumb,
                            parse_mode=PM.HTML,
                            disable_content_type_detection=True,
                        )
                    )

            self.log.info("Sending media group...")
            if self.update.effective_message and (
                post := await reply_media_group(
                    self.update.effective_message,
                    media=media_group,
                    do_quote=not self.chat.delete_link,
                )
            ):
                self.log.info("Sent media group.")
                self.sent_any = True
                if not doc_group:
                    return
                self.log.info("Sending document group...")
                if await reply_media_group(
                    post[0],
                    media=doc_group,
                    do_quote=True,
                ):
                    self.log.info("Sent document group.")
        for item in items:
            try:
                item.path.unlink(missing_ok=True)
                if item.thumb_path:
                    item.thumb_path.unlink(missing_ok=True)
                if item.orig_path:
                    item.orig_path.unlink(missing_ok=True)
                # Remove from the global set so _cleanup doesn't try again
                self.storage.discard(item.path)
            except Exception as exception:
                self.log.warning("Incremental cleanup failed: %r.", exception)

        # Force garbage collector
        gc.collect()

    async def download_helper(
        self,
        url: str,
        headers: Optional[dict] = None,
        **kwargs,
    ) -> tuple[Optional[Path], Optional[Path]]:
        """Downloads a file, saves it to storage_dir, and tracks it for cleanup."""
        # HLS / YouTube
        if ".m3u8" in url or "googlevideo.com" in url or "youtube.com" in self.link.link:
            loop = asyncio.get_event_loop()
            try:
                self.log.info("Attempt 1: Downloading via direct URL...")
                filepath = self.storage_dir / f"{self.update_id}_yt_direct.mp4"
                ydl_opts_direct = {
                    **ydl_opts_base,
                    "cookiefile": StringIO(
                        Fernet(bot_settings.yt_key)
                        .decrypt(bot_settings.yt_cookies.encode())
                        .decode()
                    ),
                    "outtmpl": str(filepath),
                    "headers": headers or {},
                }
                await loop.run_in_executor(
                    None, lambda: YoutubeDL(ydl_opts_direct).download([url])
                )
                if filepath.exists() and filepath.stat().st_size > 0:
                    self.log.info("Attempt 1 successful.")
                else:
                    raise Exception("File empty or missing after Attempt 1.")

            except Exception as e:
                self.log.warning("Attempt 1 failed: %r. Switching to fallback...", e)

            try:
                self.log.info("Attempt 2: Downloading via Original Source Link...")
                filepath = self.storage_dir / f"{self.update_id}_{self.link.id}.mp4"
                ydl_opts_fallback = {
                    **ydl_opts_base,
                    "cookiefile": StringIO(
                        Fernet(bot_settings.yt_key)
                        .decrypt(bot_settings.yt_cookies.encode())
                        .decode()
                    ),
                    "outtmpl": str(filepath),
                    "headers": headers or {},
                }
                await loop.run_in_executor(
                    None, lambda: YoutubeDL(ydl_opts_fallback).download([self.link.link])
                )
                if not filepath.exists():
                    filepath = filepath.with_suffix(".mp4.webm")
                if filepath.exists() and filepath.stat().st_size > 0:
                    self.log.info("Attempt 2 successful.")

            except Exception as e:
                self.log.error("Attempt 2 (Fallback) failed: %r", e)

            if not filepath.exists():
                return None, None
        else:
            if not (temppath := await save_file(url, headers=headers, **kwargs)):
                return None, None

            if not (filename := await make_file_name(self.SERVICE, url, temppath)):
                return None, None

            filepath = move_file(temppath, self.storage_dir / filename)
        self.storage.add(filepath)

        procpath = filepath

        # image processing
        if filepath.suffix.lower() in {".jiff", ".jpg", ".jpeg", ".png", ".webp"}:
            if not (procpath := await process_image(filepath)):
                self.log.error("Couldn't resize image: %s", filepath.name)
                raise SenderError(
                    message="contains images the bot couldn't resize!",
                    telegram_message="contains images the bot couldn't resize\\!",
                )
            procpath = Path(procpath)
            if procpath != filepath:
                resized_name = f"RE_{filepath.stem}{filepath.suffix}"
                procpath = move_file(procpath, self.storage_dir / resized_name)
                self.storage.add(procpath)

        # video processing
        elif filepath.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
            if not (processed_video := await process_video(filepath)):
                self.log.error("Couldn't process video: %s", filepath.name)
                raise SenderError(
                    message="contains videos the bot couldn't process!",
                    telegram_message="contains videos the bot couldn't process\\!",
                )

            procpath = Path(processed_video)
            if procpath != filepath:
                self.storage.add(procpath)

        return procpath, filepath

    def _cleanup(self):
        """Deletes all tracked files and the directory."""
        self.log.debug(
            "Cleaning up storage for update %s: %s.", self.update_id, self.storage
        )
        delete_files(self.storage)

        try:
            if self.storage_dir.exists():
                self.storage_dir.rmdir()
        except Exception as exception:
            self.log.warning("Could not remove storage directory: %r.", exception)

        # Force garbage collector
        gc.collect()

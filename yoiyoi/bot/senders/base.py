"""Base for media senders"""

from abc import ABC, abstractmethod
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# structured logging
import structlog

# telegram core bot api
from telegram import InputMediaDocument, InputMediaPhoto, InputMediaVideo, Update

# telegram constants
from telegram.constants import MediaGroupLimit as MGL
from telegram.constants import ParseMode as PM

# cache dir
from yoiyoi.bot import CACHE_DIR

# telegrm senders
from yoiyoi.bot.formatters import make_file_name
from yoiyoi.bot.processors import process_image
from yoiyoi.bot.senders.telegram import send_error, send_media_group
from yoiyoi.extra.requests import save_file
from yoiyoi.extra.utils import delete_files, move_file

# http requests

# setup logger
log = structlog.get_logger(__name__)


@dataclass
class MediaItem:
    path: Path
    type: str  # 'video', 'photo'
    caption: str = ""
    thumb_path: Path = None
    orig_path: Path = None
    width: int = 0
    height: int = 0
    duration: int = 0


class BaseSender(ABC):
    SERVICE: str = None

    def __init__(self, update: Update, link: object, chat: object):
        if self.SERVICE is None:
            raise NotImplementedError(
                f"Class {self.__class__.__name__} must define a 'SERVICE' attribute."
            )

        self.update = update
        self.link = link
        self.chat = chat
        self.update_id = update.update_id

        # setup storage
        self.storage_dir = Path(CACHE_DIR / str(self.update_id))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.files_to_clean = set()
        self.storage = set()

    @abstractmethod
    async def get_media_generator(self):
        """Yields MediaItem objects one by one."""
        pass

    async def run(self):
        """Main entry point."""
        try:
            generator = self.get_media_generator()
            await self._send_batched(generator)

        except Exception as exception:
            log.error(
                "Error in %s: %r.",
                self.__class__.__name__,
                exception,
                exc_info=True,
                # function info
                chat=self.chat,
                storage=self.storage,
            )
        finally:
            self._cleanup()

    async def _send_batched(self, generator):
        """Processes items in chunks with automatic memory flushing."""
        batch_items = []

        async for item in generator:
            batch_items.append(item)

            if len(batch_items) == MGL.MAX_MEDIA_LENGTH:
                await self._process_and_flush(batch_items)
                batch_items.clear()

        if batch_items:
            await self._process_and_flush(batch_items)

    async def _process_and_flush(self, items):
        """Opens files, sends to Telegram, and closes everything immediately."""
        with ExitStack() as stack:
            media_group = []
            doc_group = []

            for idx, item in enumerate(items):
                media_handle = stack.enter_context(item.path.open("rb"))
                caption = item.caption if idx == 0 else None

                # Build Telegram objects
                if item.type == "video":
                    thumb_handle = None
                    if item.thumb_path:
                        thumb_handle = stack.enter_context(item.thumb_path.open("rb"))

                    media_group.append(
                        InputMediaVideo(
                            media=media_handle,
                            thumbnail=thumb_handle,
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
                            media=media_handle,
                            caption=caption,
                            parse_mode=PM.HTML,
                        )
                    )

                if item.orig_path:
                    doc_handle = stack.enter_context(item.orig_path.open("rb"))
                    doc_group.append(
                        InputMediaDocument(
                            media=doc_handle,
                            parse_mode=PM.HTML,
                            disable_content_type_detection=True,
                        )
                    )

            log.info("Sending media group...")
            if post := await send_media_group(
                self.update.effective_message,
                media=media_group,
                do_quote=not self.chat.delete_link,
            ):
                log.info("Sent media group.")
                if not doc_group:
                    return
                log.info("Sending document group...")
                if await send_media_group(post[0], media=doc_group, do_quote=True):
                    log.info("Sent document group.")
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
                log.warning("Incremental cleanup failed: %r.", exception)

    async def download_helper(self, url: str, headers: dict = None) -> Optional[Path]:
        """Downloads a file, saves it to storage_dir, and tracks it for cleanup."""
        if not (temp_path := await save_file(url, headers=headers)):
            return None
        filename = await make_file_name(self.SERVICE, url, temp_path)
        filepath = move_file(temp_path, self.storage_dir / filename)
        self.storage.add(filepath)

        if filepath.suffix.lower() in (".jiff", ".jpg", ".jpeg", ".png", ".webp"):
            if not (imagepath := await process_image(filepath)):
                log.error("Couldn't resize image: %s", filepath.name)
                await send_error(
                    self.update,
                    f"Post from {self.SERVICE} contains images the bot couldn't resize!",
                    do_quote=not self.chat.delete_link,
                )
                return None

            imagepath = Path(imagepath)
            if imagepath != filepath:
                resized_name = f"RE_{filepath.stem}{filepath.suffix}"
                filepath = move_file(imagepath, self.storage_dir / resized_name)
                self.storage.add(filepath)

        return filepath

    def _cleanup(self):
        """Deletes all tracked files and the directory."""
        log.debug("Cleaning up storage for update %s: %s.", self.update_id, self.storage)
        delete_files(self.storage)

        try:
            if self.storage_dir.exists():
                self.storage_dir.rmdir()
        except Exception as exception:
            log.warning("Could not remove storage directory: %r.", exception)

"""Bot Functions"""
import asyncio
import logging
import os

from hashlib import sha256
from html import escape as escape_html
from pathlib import Path
from typing import Optional

# parse json
import orjson

# working with images
from PIL import Image

# pyrogram types
from pyrogram.types import InputMediaDocument, InputMediaPhoto, InputMediaVideo

# telegram core bot api
from telegram import Update

# telegram constants
from telegram.constants import MessageLimit as ML

# telegram errors
from telegram.error import BadRequest

# telegram core bot api extension
from telegram.ext import CallbackContext

# link types and other info
from ..api import LinkType, TikTokMediaKind

# instagram api
from ..api.instagram import get_instagram_links

# Link & TweetContent namedtuples
from ..api.namedtuples import Link, TweetContent

# pixiv api
from ..api.pixiv import get_pixiv_links

# tiktok api
from ..api.tiktok import get_tiktok_links

# twitter api
from ..api.twitter import get_twitter_links

# youtube api
from ..api.youtube_short import get_youtube_short_links

# get constants and pyrogram app
from ..bot import QUEUE_SIZE, PixivParse

# bot formatters
from ..bot.formatters import (
    esc,
    formatter,
    get_text,
    join_file_name,
    make_file_name,
    pixiv_parse,
)

# bot helpers
from ..bot.helpers import notify

# bot senders
from ..bot.senders import get_message, send_error, send_media_group, send_reply

# database table
from ..db.models import Chat

# database helpers
from ..db.updaters import update_chat

# get file size
from ..extra.request_helpers import PIXIV_HEADERS, save_file

# media styles
from ..extra.styles import PixivStyle, TikTokStyle, TwitterStyle, YouTubeShortStyle

# extra utilities
from ..extra.utils import delete_files, get_file_chunk, move_file

# setup logger
log = logging.getLogger(__name__)

# update queue limiter
update_queue = asyncio.Queue(QUEUE_SIZE)

# current media groups
media_groups = set()

# telegram image max size
MAX_SIZE = (2560, 2560)

# telegram max photo size sum
MAX_PHOTO_SIZE_SUM = 10000

# telegram max photo size (10 MB)
MAX_PHOTO_FILE_SIZE = 10 << 20

# presumed max gif file size (3 MB)
MAX_GIF_FILE_SIZE = 3 << 20

# cache directory
CACHE_DIR = Path(".") / os.environ.get("CACHE_DIR", ".cache")


class ImageResizeException(Exception):
    pass


async def count_audio_stream(update: Update, filepath: Path) -> bool:
    update_id = update.update_id
    log.info("[%d] Checking for audio streams...", update_id)
    # fmt: off
    ffprobe_command = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "a:0",
        str(filepath),
    ]
    # fmt: on
    log.debug("[%d] ffprobe command: %s.", update_id, " ".join(ffprobe_command))
    process = await asyncio.create_subprocess_exec(
        *ffprobe_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if await process.wait() != 0:
        log.warning("[%d] ffprobe command failed.", update_id)
    try:
        output = await process.stdout.read()
        result = orjson.loads(output)
    except orjson.JSONDecodeError:
        log.warning("[%d] Couldn't parse output: %s.", update_id, output)
        log.warning("[%d] Assuming 0 audio streams...", update_id)
        return 0
    return len(result["streams"])


async def process_video(update: Update, filepath: Path) -> Optional[Path]:
    update_id = update.update_id
    log.info("[%d] Processing a video...", update_id)
    # if more than 0 audio streams then quit
    if await count_audio_stream(update, filepath):
        log.info("[%d] Found an audio stream!", update_id)
        return filepath
    log.info("[%d] Found no audio streams!", update_id)
    # rename and create output path
    result_path = filepath.parent / filepath.name.replace(".mov", ".mp4")
    rename_path = filepath.rename(
        filepath.parent / f"RE_{filepath.name.replace('.mov', '.mp4')}"
    )
    log.debug("[%d] Output video: %s.", update_id, result_path)
    # fmt: off
    ffmpeg_command = (
        "ffmpeg",
        "-hide_banner", "-loglevel", "warning",
        "-i", str(rename_path),
        "-f", "lavfi", "-t", "1", "-i", "anullsrc=r=44100:cl=stereo",
        "-c:v", "copy",
        str(result_path),
    )
    # fmt: on
    log.debug("[%d] ffmpeg command: %s.", update_id, " ".join(ffmpeg_command))
    process = await asyncio.create_subprocess_exec(*ffmpeg_command)
    if await process.wait() != 0:
        log.warning("[%d] ffmpeg command failed.", update_id)
    original = sha256(get_file_chunk(rename_path)).hexdigest()
    output = sha256(get_file_chunk(result_path)).hexdigest()
    log.debug("[%d] SHA256 input  hash: %s.", update_id, original)
    log.debug("[%d] SHA256 output hash: %s.", update_id, output)
    if original == output:
        log.info("[%d] SHA256 hashes are the same, deleting output...", update_id)
        result_path.unlink(missing_ok=True)
        return rename_path.rename(result_path)
    else:
        log.info("[%d] SHA256 hashes are different, sending output...", update_id)
        rename_path.unlink(missing_ok=True)
        return result_path


async def resize_image(filepath: Path):
    if (resizer_api := os.environ.get("RESIZER_API", None)) and (
        resized_filepath := await save_file(
            resizer_api,
            "POST",
            timeout=120,
            files={"upload_file": filepath.open("rb")},
        )
    ):
        return resized_filepath


async def process_image(update: Update, filepath: Path) -> Optional[Path]:
    update_id = update.update_id
    log.info("[%d] Processing an image...", update_id)
    # check if file size > 10 MB
    if (filesize := os.stat(filepath).st_size) > MAX_PHOTO_FILE_SIZE:
        log.debug("[%d] File size: %d.", update_id, filesize)
        return await resize_image(filepath)
    # check if width + height > 10000
    with Image.open(filepath) as image:
        log.debug("[%d] Original: %d x %d.", update_id, *image.size)
        log.debug("[%d] Size sum: %d.", update_id, sum(image.size))
        if sum(image.size) > MAX_PHOTO_SIZE_SUM:
            return await resize_image(filepath)
    return filepath


async def choose_twitter_video(
    update: Update,
    content: TweetContent,
) -> Optional[str]:
    for link, size in zip(content.links, content.sizes, strict=False):
        if size > 50 << 20:
            await send_error(update, "Sorry, file is *too huge*\\!")
            await send_reply(update, f"[Download link]({link})\\.")
            await send_reply(update, "Trying to get smaller version\\.\\.\\.")
            continue
        return link
    return


async def send_collection(
    update: Update,
    chat: Chat,
    storage: set,
    files: list,
    docs: list = None,
):
    update_id = update.update_id
    try:
        message = await get_message(update)
        quoted = not (chat.delete_link or chat.include_link)
        i, j = 0, 10
        while i < len(files):
            # send media group
            log.info("[%d] Sending media group...", update_id)
            if post := await send_media_group(message, media=files[i:j], quote=quoted):
                log.info("[%d] Sent media group.", update_id)
            # send document group
            if docs and post:
                log.info("[%d] Sending document group...", update_id)
                if await send_media_group(post[0], media=docs[i:j], quote=True):
                    log.info("[%d] Sent document group.", update_id)
            # get next 10 photos/docs
            i, j = j, j + 10
        # seems to be successful
        return True
    except Exception as exception:
        log.warning(
            "Failed to send files because of %s: %r.",
            exception.__class__.__name__,
            exception,
        )
        return False
    finally:
        # delete all files
        log.debug("Storage: %s.", storage)
        delete_files(storage)
        Path(CACHE_DIR / str(update_id)).rmdir()


async def send_twitter(
    update: Update,
    link: Link,
    chat: Chat,
) -> None:
    """Sends twitter media

    Args:
        update (Update): current update
        link (Link): tweet link
        chat (Chat): current chat
    """
    # notify(update, function="send_twitter")
    update_id = update.update_id
    error_text = f"[*This twitter content*]({link.link}) "
    log.info("[%d] Twitter Link: %s.", update_id, link.link)
    # get media
    if (tweet := await get_twitter_links(link.id)) and (count := len(tweet.content)):
        info = None
        if chat.include_link:
            info = TwitterStyle.get_format(chat.tw_style, tweet)
            if link.info:
                info = f"{escape_html(link.info)}\n\n{info}"
            if len(info) > ML.CAPTION_LENGTH:
                info = info[: (ML.CAPTION_LENGTH - 6)].rsplit(None, 1)[0] + r"\.\.\."
        ids = tuple(range(1, count + 1))
        parsed_ids = await pixiv_parse(update, link.illust, count)
        if link.illust:
            match parsed_ids[0]:
                case PixivParse.SUCCESS:
                    ids = parsed_ids[1]
                case PixivParse.OUT_OF_RANGE:
                    error_text += (
                        "can't be sent, because the bot "
                        "*can't* send more than 10 files\\!"
                    )
                case PixivParse.NOT_WITHIN_RANGE:
                    error_text += (
                        "can't be sent, because the numbers "
                        "are *not within* range: "
                        f"\\[`1`\\-`{count}`\\]\\!"
                    )
                case PixivParse.NO_INFO:
                    error_text += (
                        "can't be sent, because the bot requires "
                        "the order of illustrations to be specified "
                        "with \\[`link`\\] `+` \\[`ids`\\] syntax\\! "
                        "See */help* for more info\\.\n\n"
                        "Choose illustrations in range: "
                        f"\\[`1`\\-`{count}`\\]\\.\n"
                    )
                case _:
                    error_text += (
                        "can't be sent, because something went wrong "
                        "while parsing your input."
                    )
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        for idx in ids:
            media = tweet.content[idx - 1]
            if media.type == "photo":
                filepath = await save_file(media.links[0])
                filename = await join_file_name("twitter", media.links[0], filepath)
                filepath = move_file(filepath, storage_folder / filename)
                storage.add(filepath)
                log.debug("[%d] Filename: %r.", update_id, filename)
                if not (imagepath := await process_image(update, filepath)):
                    log.error("[%d] Couldn't resize image.", update.update_id)
                    await send_error(
                        update,
                        error_text + "contains images the bot couldn't resize\\!",
                        quote=not (chat.delete_link or chat.include_link),
                    )
                    return
                if (imagepath := Path(imagepath)) != filepath:
                    imagepath = move_file(imagepath, storage_folder / f"RE_{filename}")
                    storage.add(imagepath)
                # add to collection
                files.append(InputMediaPhoto(imagepath, info if idx == ids[0] else None))
                if chat.tw_orig:
                    docs.append(InputMediaDocument(filepath))
            else:
                if not (videolink := await choose_twitter_video(update, media)):
                    log.error("[%d] Couldn't get links.", update.update_id)
                    await send_error(
                        update,
                        error_text + "contains videos the bot couldn't send\\!",
                        quote=not (chat.delete_link or chat.include_link),
                    )
                    return
                filepath = await save_file(videolink)
                filename = await join_file_name("twitter", videolink, filepath)
                filepath = move_file(filepath, storage_folder / filename)
                storage.add(filepath)
                if media.type == "gif" or os.stat(filepath).st_size < MAX_GIF_FILE_SIZE:
                    if not (videopath := await process_video(update, filepath)):
                        log.error("[%d] Couldn't add sound to video.", update.update_id)
                        await send_error(
                            update,
                            error_text + "contains videos the bot couldn't send\\!",
                            quote=not (chat.delete_link or chat.include_link),
                        )
                        return
                else:
                    videopath = filepath
                if (videopath := Path(videopath)) != filepath:
                    storage.add(videopath)
                # add to collection
                files.append(InputMediaVideo(videopath, None, info if idx == ids[0] else None))
        log.debug("[%d] Finished adding to collection.", update_id)
        log.debug("[%d] Caption: %r.", update_id, info)
        if await send_collection(update, chat, storage, files, docs):
            return
    # if no links returned
    log.error("[%d] Couldn't get twitter content.", update_id)
    await send_error(
        update,
        error_text
        + (
            "can't be found or downloaded\\. "
            "If this seems to be wrong, try again later\\."
        ),
        quote=not (chat.delete_link or chat.include_link),
    )


async def send_instagram(
    update: Update,
    link: Link,
    chat: Chat,
) -> None:
    """Sends instagram media

    Args:
        update (Update): current update
        link (Link): instagram link
        chat (Chat): current chat
    """
    # notify(update, function="send_instagram")
    update_id = update.update_id
    error_text = f"[*This instagram content*]({link.link}) "
    log.info("[%d] Instagram Link: %s.", update_id, link.link)
    # get media
    if media := await get_instagram_links(link.link):
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        info = media[0].source if chat.include_link else None
        for idx, item in enumerate(media):
            filepath = await save_file(item.link)
            if not (filename := item.name):
                filename = await join_file_name("instagram", item.link, filepath)
            else:
                filename = await make_file_name(filename, filepath)
            filepath = move_file(filepath, storage_folder / filename)
            storage.add(filepath)
            log.debug("[%d] Filename: %r.", update_id, filename)
            if item.type == "image":
                if not (imagepath := await process_image(update, filepath)):
                    log.error("[%d] Couldn't resize image.", update.update_id)
                    await send_error(
                        update,
                        error_text + "contains images the bot couldn't resize\\!",
                        quote=not (chat.delete_link or chat.include_link),
                    )
                    return
                if (imagepath := Path(imagepath)) != filepath:
                    imagepath = move_file(imagepath, storage_folder / f"RE_{filename}")
                    storage.add(imagepath)
                files.append(InputMediaPhoto(imagepath, info if not idx else None))
                if chat.in_orig:
                    docs.append(InputMediaDocument(filepath))
            if item.type == "video":
                files.append(InputMediaVideo(filepath, None, info if not idx else None))
        log.debug("[%d] Finished adding to collection.", update_id)
        log.debug("[%d] Caption: %r.", update_id, info)
        if await send_collection(update, chat, storage, files, docs):
            return
    # if no links returned
    log.error("[%d] Couldn't get instagram content.", update_id)
    await send_error(
        update,
        error_text
        + (
            "can't be found or downloaded\\. "
            "If this seems to be wrong, try again later\\."
        ),
        quote=not (chat.delete_link or chat.include_link),
    )


async def send_tiktok(
    update: Update,
    link: Link,
    chat: Chat,
) -> None:
    """Sends tiktok video

    Args:
        update (Update): current update
        link (Link): tiktok link
        chat (Chat): current chat
    """
    # notify(update, function="send_tiktok")
    update_id = update.update_id
    error_text = f"[*This tiktok content*]({link.link}) "
    log.info("[%d] TikTok Link: %s.", update_id, link.link)
    # get media
    if media := await get_tiktok_links(link.link):
        info = None
        if chat.include_link:
            info = TikTokStyle.get_format(chat.tt_style, media)
            if len(info) > ML.CAPTION_LENGTH:
                info = info[: (ML.CAPTION_LENGTH - 6)].rsplit(None, 1)[0] + r"\.\.\."
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        if media.kind == TikTokMediaKind.SLIDESHOW and chat.tt_slide_mode == 1:
            media_photos = media.content[2:]
            i, j = 0, 10
            while i < len(media_photos):
                for idx, media_photo in enumerate(media_photos[i:j], i):
                    filelink = media_photo.link
                    filepath = await save_file(filelink)
                    if not (filename := media_photo.name):
                        filename = await join_file_name("tiktok", filelink, filepath)
                    else:
                        filename = await make_file_name(filename, filepath)
                    filepath = move_file(filepath, storage_folder / filename)
                    storage.add(filepath)
                    log.debug("[%d] Filename: %r.", update_id, filename)
                    if not (imagepath := await process_image(update, filepath)):
                        log.error("[%d] Couldn't resize image.", update.update_id)
                        await send_error(
                            update,
                            error_text + "contains images the bot couldn't resize\\!",
                            quote=not (chat.delete_link or chat.include_link),
                        )
                        return
                    if (imagepath := Path(imagepath)) != filepath:
                        imagepath = move_file(
                            imagepath, storage_folder / f"RE_{filename}"
                        )
                        storage.add(imagepath)
                    files.append(InputMediaPhoto(imagepath, info if idx == i else None))
                    if chat.tt_orig:
                        docs.append(InputMediaDocument(filepath))
                # get next 10 photos/docs
                i, j = j, j + 10
        else:
            videos = media.content[:2]
            # check size
            filepath = None
            for vid in videos:
                if 0 < vid.size < 50 << 20:
                    filepath = await save_file(vid.link)
                    break
            else:
                # if file is too big
                error_text += "can't be sent, because video file is too big\\!"
                log.error("[%d] Video file is too big.", update_id)
            # upload video if any
            if filepath:
                filename = await make_file_name(str(media.id), filepath)
                videopath = move_file(filepath, storage_folder / filename)
                storage.add(videopath)
                files.append(InputMediaVideo(videopath, None, info))
        if files:
            log.debug("[%d] Finished adding to collection.", update_id)
            log.debug("[%d] Caption: %r.", update_id, info)
            if await send_collection(update, chat, storage, files, docs):
                return
    # if there is no video
    else:
        log.error("[%d] Couldn't get tiktok content.", update_id)
        error_text += (
            "can't be found or downloaded\\! If this seems to be wrong, try "
            "again later\\."
        )
    await send_error(
        update,
        error_text,
        quote=not (chat.delete_link or chat.include_link),
    )


async def send_youtube_short(
    update: Update,
    link: Link,
    chat: Chat,
) -> None:
    """Sends youtube short video

    Args:
        update (Update): current update
        link (Link): youtube short link
        chat (Chat): current chat
    """
    # notify(update, function="send_youtube_short")
    update_id = update.update_id
    error_text = f"[*This youtube content*]({link.link}) "
    log.info("[%d] YouTube Short Link: %s.", update_id, link.link)
    # get media
    if video := await get_youtube_short_links(link):
        info = None
        if chat.include_link:
            info = YouTubeShortStyle.get_format(chat.yts_style, video)
            if len(info) > ML.CAPTION_LENGTH:
                info = info[: (ML.CAPTION_LENGTH - 6)].rsplit(None, 1)[0] + r"\.\.\."
        # check size
        files, storage = [], set()
        storage_folder = Path(CACHE_DIR / str(update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        filepath = None
        for vid in video.content:
            if 0 < vid.size < 50 << 20:
                filepath = await save_file(vid.link)
                break
        else:
            # if file is too big
            error_text += "can't be sent, because video file is too big\\!"
            log.error("[%d] Video file is too big.", update_id)
        # upload video if any
        if filepath:
            filename = await make_file_name(video.id, filepath)
            videopath = move_file(filepath, storage_folder / filename)
            storage.add(videopath)
            files.append(InputMediaVideo(videopath, None, info))
            log.debug("[%d] Finished adding to collection.", update_id)
            log.debug("[%d] Caption: %r.", update_id, info)
            if await send_collection(update, chat, storage, files):
                return
    # if there is no video
    log.error("[%d] Couldn't get youtube short content.", update_id)
    error_text += (
        "can't be found or downloaded\\! If this seems to be wrong, try " "again later\\."
    )
    await send_error(
        update,
        error_text,
        quote=not (chat.delete_link or chat.include_link),
    )


async def send_pixiv(
    update: Update,
    link: Link,
    chat: Chat,
) -> None:
    """Sends pixiv artwork

    Args:
        update (Update): current update
        link (Link): pixiv artwork link
        chat (Chat): current chat
    """
    # notify(update, function="send_pixiv")
    update_id = update.update_id
    error_text = f"[*This pixiv content*]({link.link}) "
    log.info("[%d] Pixiv Link: %s.", update_id, link.link)
    # get media
    if (art := await get_pixiv_links(link.id)) and (count := len(art.content)):
        info = None
        if chat.include_link:
            info = PixivStyle.get_format(chat.px_style, art)
            if link.info:
                info = f"{esc(link.info)}\n\n{info}"
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        ids = [1]
        parsed_ids = await pixiv_parse(update, link.illust, count)
        if art.type == "ugoira":
            media = art.content[0]
            filepath = await save_file(media.original)
            filename = await join_file_name("pixiv", media.original, filepath)
            filepath = move_file(filepath, storage_folder / filename)
            storage.add(filepath)
            if not (videopath := await process_video(update, filepath)):
                log.error("[%d] Couldn't add sound to video.", update.update_id)
                await send_error(
                    update,
                    error_text + "contains videos the bot couldn't send\\!",
                    quote=not (chat.delete_link or chat.include_link),
                )
                return
            if (videopath := Path(videopath)) != filepath:
                storage.add(videopath)
            # add to collection
            files.append(InputMediaVideo(videopath, None, info))
        else:
            if count > 1:
                ids = []
                match parsed_ids[0]:
                    case PixivParse.SUCCESS:
                        ids = parsed_ids[1]
                    case PixivParse.OUT_OF_RANGE:
                        error_text += (
                            "can't be sent, because the bot "
                            "*can't* send more than 10 files\\!"
                        )
                    case PixivParse.NOT_WITHIN_RANGE:
                        error_text += (
                            "can't be sent, because the numbers "
                            "are *not within* range: "
                            f"\\[`1`\\-`{count}`\\]\\!"
                        )
                    case PixivParse.NO_INFO:
                        error_text += (
                            "can't be sent, because the bot requires "
                            "the order of illustrations to be specified "
                            "with \\[`link`\\] `+` \\[`ids`\\] syntax\\! "
                            "See */help* for more info\\.\n\n"
                            "Choose illustrations in range: "
                            f"\\[`1`\\-`{count}`\\]\\.\n"
                        )
                    case _:
                        error_text += (
                            "can't be sent, because something went wrong "
                            "while parsing your input."
                        )
            i, j = 0, 10
            while i < len(ids):
                for idx in ids[i:j]:
                    media = art.content[idx - 1]
                    filelink = media.original
                    filepath = await save_file(filelink, headers=PIXIV_HEADERS)
                    filename = await join_file_name("pixiv", filelink, filepath)
                    filepath = move_file(filepath, storage_folder / filename)
                    storage.add(filepath)
                    log.debug("[%d] Filename: %r.", update_id, filename)
                    if not (imagepath := await process_image(update, filepath)):
                        log.error("[%d] Couldn't resize image.", update.update_id)
                        await send_error(
                            update,
                            error_text + "contains images the bot couldn't resize\\!",
                            quote=not (chat.delete_link or chat.include_link),
                        )
                        return
                    if (imagepath := Path(imagepath)) != filepath:
                        imagepath = move_file(
                            imagepath, storage_folder / f"RE_{filename}"
                        )
                        storage.add(imagepath)
                    files.append(
                        InputMediaPhoto(imagepath, info if ids[i] == idx else None)
                    )
                    if chat.px_orig:
                        docs.append(InputMediaDocument(filepath))
                # get next 10 photos/docs
                i, j = j, j + 10
        if files:
            log.debug("[%d] Finished adding to collection.", update_id)
            log.debug("[%d] Caption: %r.", update_id, info)
            if await send_collection(update, chat, storage, files, docs):
                return
    else:
        log.error("[%d] Couldn't get pixiv content.", update_id)
        error_text += (
            "can't be found or downloaded\\. If this seems to be wrong, try "
            "again later\\."
        )
    await send_error(
        update,
        error_text,
        quote=not (chat.delete_link or chat.include_link),
    )


async def process_link(update: Update, _: CallbackContext) -> None:
    """Answers to user's links

    Args:
        update (Update): current update
        _ (CallbackContext): current context
    """
    notify(update, function="process_link")
    update_id = update.update_id
    # get current chat
    chat = await update_chat(update.effective_chat)
    # check if message is forwarded and if chat should ignore it
    if update.effective_message.forward_date and chat.ignore_fw:
        return
    # get media group id
    media_group_id = update.effective_message.media_group_id
    # put into limited queue
    await update_queue.put(update.update_id)
    try:
        should_delete = False
        # check for text
        if text := await get_text(update):
            # add media group id if needed
            log.debug("[%d] Received text: %r.", update_id, text)
            async for link in formatter(update_id, text):
                if not should_delete:
                    should_delete = True
                    if media_group_id:
                        media_groups.add(media_group_id)
                match link.type:
                    case LinkType.TWITTER:
                        await send_twitter(update, link, chat)
                    case LinkType.INSTAGRAM:
                        await send_instagram(update, link, chat)
                    case LinkType.TIKTOK:
                        await send_tiktok(update, link, chat)
                    case LinkType.YOUTUBE_SHORT:
                        await send_youtube_short(update, link, chat)
                    case LinkType.PIXIV:
                        await send_pixiv(update, link, chat)
                    case _:
                        await send_reply(update, esc(link.link))
        # delete source post media group messages
        else:
            should_delete = media_group_id in media_groups
        # delete if should
        if chat.delete_link and should_delete:
            try:
                await update.effective_message.delete()
            except BadRequest:
                log.warning("Message to delete not found.")
    finally:
        # mark done and remove from limited queue
        update_queue.task_done()
        await update_queue.get()
        # clear media groups
        if update_queue.empty():
            media_groups.clear()

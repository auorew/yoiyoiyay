import asyncio
import os

from hashlib import sha256
from pathlib import Path
from typing import Optional

# parse json
import orjson

# structured logging
import structlog

# working with images
from PIL import Image

# working with heif (just in case)
from pillow_heif import register_heif_opener

# telegram core bot api
from telegram import Update

# app utils
from yoiyoi.app.utils import convert_media_file, resize_image_file

# get constants
from yoiyoi.bot import (
    MAX_PHOTO_FILE_SIZE,
    MAX_PHOTO_SIZE_SUM,
    MAX_VIDEO_DURATION,
    MAX_VIDEO_SIZE,
)

# bot formatters
from yoiyoi.bot.formatters import esc

# bot senders
from yoiyoi.bot.senders import send_error, send_reply

# get file size
from yoiyoi.extra.requests import save_file

# settings
from yoiyoi.extra.settings import bot_settings

# extra utilities
from yoiyoi.extra.utils import get_file_chunk, replace_file

# TweetContent namedtuples
from yoiyoi.services.namedtuples import TweetContent

# setup logger
log = structlog.get_logger(__name__)

# enable heif support for pillow
register_heif_opener()


def _crop_thumbnail_sync(thumbpath: Path, video_width: int, video_height: int) -> bool:
    """Synchronous worker that performs the actual cropping."""
    # Safe temporary path using stem/suffix manipulation
    newthumbpath = thumbpath.with_name(f"{thumbpath.stem}_rethumb{thumbpath.suffix}")

    try:
        with Image.open(thumbpath) as image:
            image_width, image_height = image.size

            # Calculate target crop width preserving original video aspect ratio
            thumbnail_width = video_width * image_height / video_height

            # Center-crop horizontal bounding box
            top, bottom = 0, image_height
            left = (image_width - thumbnail_width) / 2
            right = left + thumbnail_width

            # Crop and save as JPEG
            cropped_img = image.crop((left, top, right, bottom))
            cropped_img.save(newthumbpath, quality=95)

        replace_file(newthumbpath, thumbpath)
        return True

    except Exception as exception:
        log.warning(
            "Failed to crop thumbnail for %s because of %s: %r.",
            thumbpath,
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            thumbpath=thumbpath,
            video_width=video_width,
            video_height=video_height,
        )
        if newthumbpath.exists():
            newthumbpath.unlink(missing_ok=True)
        return False


async def crop_thumbnail(thumbpath: Path, video_width: int, video_height: int) -> bool:
    """Async entry point — offloads blocking image operations to a thread."""
    return await asyncio.to_thread(
        _crop_thumbnail_sync, thumbpath, video_width, video_height
    )


async def count_audio_stream(filepath: Path) -> bool:
    log.info("Checking for audio streams...")
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
    log.debug("ffprobe command: %s.", " ".join(ffprobe_command))
    process = await asyncio.create_subprocess_exec(
        *ffprobe_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if await process.wait() != 0:
        log.warning("ffprobe command failed.")
    try:
        output = await process.stdout.read()
        result = orjson.loads(output)
    except orjson.JSONDecodeError:
        log.warning("Couldn't parse output: %s.", output)
        log.warning("Assuming 0 audio streams...")
        return 0
    if not result:
        return 0
    return len(result["streams"])


async def process_video(filepath: Path) -> Path:
    log.info("Processing a video...")
    # if more than 0 audio streams then quit
    if await count_audio_stream(filepath):
        log.info("Found an audio stream!")
        return filepath
    log.info("Found no audio streams!")
    # rename and create output path
    result_path = filepath.parent / filepath.name.replace(".mov", ".mp4")
    rename_path = filepath.rename(
        filepath.parent / f"RE_{filepath.name.replace('.mov', '.mp4')}"
    )
    log.debug("Output video: %s.", result_path)
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
    log.debug("ffmpeg command: %s.", " ".join(ffmpeg_command))
    process = await asyncio.create_subprocess_exec(*ffmpeg_command)
    if await process.wait() != 0:
        log.warning("ffmpeg command failed.")
    original = sha256(get_file_chunk(rename_path)).hexdigest()
    output = sha256(get_file_chunk(result_path)).hexdigest()
    log.debug("SHA256 input  hash: %s.", original)
    log.debug("SHA256 output hash: %s.", output)
    if original == output:
        log.info("SHA256 hashes are the same, deleting output...")
        result_path.unlink(missing_ok=True)
        return rename_path.rename(result_path)
    else:
        log.info("SHA256 hashes are different, sending output...")
        rename_path.unlink(missing_ok=True)
        return result_path


async def resize_image(filepath: Path):
    if bot_settings.resizer_local:
        resized_filepath, _, error_text = await resize_image_file(
            filepath, f"image/{filepath.suffix[1:]}"
        )
        if not error_text:
            return resized_filepath
        log.error(error_text)

    elif (resizer_api := bot_settings.resizer_api) and (
        resized_filepath := await save_file(
            resizer_api,
            "POST",
            timeout=120,
            files={"upload_file": filepath.read_bytes()},
        )
    ):
        return resized_filepath


async def convert_image(filepath: Path):
    if bot_settings.converter_local:
        converted_filepath, _, error_text = await convert_media_file(
            filepath, f"image/{filepath.suffix[1:]}"
        )
        if not error_text:
            return converted_filepath
        log.error(error_text)

    elif converter_api := bot_settings.converter_api:
        if converted_filepath := await save_file(
            converter_api,
            "POST",
            timeout=120,
            files={"upload_file": filepath.read_bytes()},
        ):
            return converted_filepath


async def process_image(filepath: Path) -> Optional[Path]:
    log.info("Processing an image...")
    # check if file size > 10 MB
    if (filesize := os.stat(filepath).st_size) > MAX_PHOTO_FILE_SIZE:
        log.debug("File size: %d.", filesize)
        return await resize_image(filepath)
    # check if width + height > 10000
    with Image.open(filepath) as image:
        log.debug("Original: %d x %d.", *image.size)
        log.debug("Size sum: %d.", sum(image.size))
        if sum(image.size) > MAX_PHOTO_SIZE_SUM:
            return await resize_image(filepath)
    return await convert_image(filepath)


async def choose_twitter_video(
    update: Update,
    content: TweetContent,
) -> Optional[str]:
    if content.duration > MAX_VIDEO_DURATION:
        video_links = ", ".join(
            [f"[\\[*{index}*\\]]({link})" for index, link in enumerate(content.links, 1)]
        )
        await send_error(
            update,
            f"Sorry, video is *too long*\\: " f"`{esc(str(content.duration))} s`\\! ",
        )
        await send_reply(update, f"Here's your download links\\: {video_links}\\.")
        return
    for link, size in zip(content.links, content.sizes, strict=False):
        if size > MAX_VIDEO_SIZE:
            await send_error(update, "Sorry, file is *too huge*\\!")
            await send_reply(update, f"[Download link]({link})\\.")
            await send_reply(update, "Trying to get smaller version\\.\\.\\.")
            continue
        return link
    return


# write a code that will create thumbnail from video file
async def create_thumbnail(filepath: Path) -> Optional[Path]:
    log.info("Creating a thumbnail...")
    # create output path
    thumbpath = filepath.parent / f"{filepath.stem}.thumb.jpg"
    # fmt: off
    ffmpeg_command = (
        "ffmpeg",
        "-hide_banner", "-loglevel", "warning",
        "-i", str(filepath),
        "-vf", "select=eq(n\\,0)",
        "-frames:v", "1",
        str(thumbpath),
    )
    # fmt: on
    log.debug("ffmpeg command: %s.", " ".join(ffmpeg_command))
    process = await asyncio.create_subprocess_exec(*ffmpeg_command)
    if await process.wait() != 0:
        log.warning("ffmpeg command failed.")
        return
    return thumbpath

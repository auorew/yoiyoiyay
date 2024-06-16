import asyncio
import logging
import os

from hashlib import sha256
from pathlib import Path
from typing import Optional

# parse json
import orjson

# working with images
from PIL import Image

# working with heif (just in case)
from pillow_heif import register_heif_opener

# telegram core bot api
from telegram import Update

# TweetContent namedtuples
from ..api.namedtuples import TweetContent

# get constants
from ..bot import MAX_PHOTO_FILE_SIZE, MAX_PHOTO_SIZE_SUM

# bot senders
from ..bot.senders import send_error, send_reply

# get file size
from ..extra.request_helpers import save_file

# extra utilities
from ..extra.utils import get_file_chunk, replace_file

# setup logger
log = logging.getLogger(__name__)

# enable heif support for pillow
register_heif_opener()


async def crop_thumbnail(thumbpath: Path, video_width: int, video_height: int):
    newthumbpath = thumbpath.parent / thumbpath.name.replace(".thumb.", ".rethumb.")
    try:
        with Image.open(thumbpath) as image:
            image_width, image_height = image.size
            # calculate thumbnail image
            thumbnail_width = video_width * image_height / video_height
            thumbnail_height = image_height
            # cropping box
            top, bottom = 0, thumbnail_height
            left = (image_width - thumbnail_width) / 2
            right = left + thumbnail_width
            # crop and save
            cropped_img = image.crop((left, top, right, bottom))
            cropped_img.save(newthumbpath, quality=95)
        replace_file(newthumbpath, thumbpath)
    except Exception as exception:
        log.warning(
            "Get video info: failed to run ffprobe command because of %s: %r.",
            exception.__class__.__name__,
            exception,
        )
        return False
    return True


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

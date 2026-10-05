import asyncio
import io
import os

from hashlib import sha256
from pathlib import Path
from typing import Optional

# parse json
import msgspec

# register jxl
import pillow_jxl  # noqa: F401

# structured logging
import structlog

# working with images
from PIL import Image, ImageOps

# working with heif (just in case)
from pillow_heif import register_heif_opener

# telegram core bot api
from telegram import Update

# app utils
from yoiyoi.app.utils import resize_image_file

# get constants
from yoiyoi.bot import (
    MAX_PHOTO_FILE_SIZE,
    MAX_PHOTO_SIZE_SUM,
    MAX_THUMB_FILE_SIZE,
    MAX_THUMB_SIZE,
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


def _process_thumbnail_sync(
    thumbpath: Path,
    video_width: Optional[int] = None,
    video_height: Optional[int] = None,
    crop: bool = True,
) -> Optional[Path]:
    """Processes an image into a Telegram-compliant JPEG thumbnail:
    - RGB mode (no alpha/palettes)
    - Stripped EXIF/ICC metadata (baseline JPEG)
    - Limit max size on longest side
    - Matches video aspect ratio
    - File size strictly < 200 kB
    """
    if not thumbpath or not thumbpath.exists() or thumbpath.stat().st_size == 0:
        return None

    target_path = thumbpath.with_suffix(".jpeg")
    temp_out = thumbpath.with_name(f"{thumbpath.stem}_thumb_tmp.jpeg")

    try:
        with Image.open(thumbpath) as raw_image:
            # 1. Correct orientation from EXIF before stripping metadata
            image = ImageOps.exif_transpose(raw_image)

            # 2. Convert to clean RGB BEFORE resizing/cropping
            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                bg = Image.new("RGB", image.size, (255, 255, 255))
                rgba_image = image.convert("RGBA")
                bg.paste(rgba_image, mask=rgba_image.split()[-1])
                image = bg
            elif image.mode != "RGB":
                image = image.convert("RGB")

            # 3. Match video aspect ratio if dimensions provided
            if video_width and video_height and video_width > 0 and video_height > 0:
                target_aspect = video_width / video_height
                img_aspect = image.width / image.height

                if crop:
                    # Center-crop thumbnail to match video aspect ratio
                    if img_aspect > target_aspect:
                        crop_w = round(target_aspect * image.height)
                        left = (image.width - crop_w) / 2
                        image = image.crop((left, 0, left + crop_w, image.height))
                    elif img_aspect < target_aspect:
                        crop_h = round(image.width / target_aspect)
                        top = (image.height - crop_h) / 2
                        image = image.crop((0, top, image.width, top + crop_h))

            # 4. Scale down so longest edge
            width, height = image.size
            if width > MAX_THUMB_SIZE or height > MAX_THUMB_SIZE:
                scale = min(MAX_THUMB_SIZE / width, MAX_THUMB_SIZE / height)
                new_w = max(1, round(width * scale))
                new_h = max(1, round(height * scale))
                image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # 5. Compress to baseline JPEG under max size (removing EXIF/ICC data)
            target_size = MAX_THUMB_FILE_SIZE - 1024
            buf = io.BytesIO()
            quality = 95

            while quality >= 20:
                buf.seek(0)
                buf.truncate()
                image.save(
                    buf,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=False,
                )
                if buf.tell() <= target_size:
                    break
                quality -= 5

            # Emergency downscale loop if compression alone exceeds limit
            while buf.tell() > target_size and image.width > 50 and image.height > 50:
                image = image.resize(
                    (int(image.width * 0.85), int(image.height * 0.85)),
                    Image.Resampling.LANCZOS,
                )
                buf.seek(0)
                buf.truncate()
                image.save(
                    buf,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=False,
                )

            temp_out.write_bytes(buf.getvalue())

        if target_path != thumbpath:
            replace_file(temp_out, target_path)
            thumbpath.unlink(missing_ok=True)
            return target_path
        else:
            replace_file(temp_out, thumbpath)
            return thumbpath

    except Exception as exception:
        log.warning(
            "Failed to process thumbnail for %s: %r.",
            thumbpath,
            exception,
            exc_info=True,
            thumbpath=thumbpath,
        )
        if temp_out.exists():
            temp_out.unlink(missing_ok=True)
        return None


async def process_thumbnail(
    thumbpath: Path,
    video_width: Optional[int] = None,
    video_height: Optional[int] = None,
    crop: bool = False,
) -> Optional[Path]:
    """Async entry point for processing thumbnails."""
    return await asyncio.to_thread(
        _process_thumbnail_sync,
        thumbpath,
        video_width,
        video_height,
        crop,
    )


def _crop_thumbnail_sync(thumbpath: Path, video_width: int, video_height: int) -> bool:
    """Synchronous worker that performs cropping and thumbnail processing."""
    result = _process_thumbnail_sync(
        thumbpath, video_width=video_width, video_height=video_height, crop=True
    )
    return bool(result)


async def crop_thumbnail(thumbpath: Path, video_width: int, video_height: int) -> bool:
    """Async entry point — crops and converts thumbnail for Telegram."""
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
        result = msgspec.json.decode(output)
    except msgspec.DecodeError:
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


async def convert_image(filepath: Path, to_ext: str = "webp"):
    if bot_settings.converter_local:
        converted_filepath, _, error_text = await resize_image_file(
            filepath, {filepath.suffix[1:]}, to_ext
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


async def process_image(filepath: Path, to_ext: str = "") -> Optional[Path]:
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
    if to_ext:
        return await convert_image(filepath, to_ext)
    return filepath


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
    log.info("Creating a thumbnail from video %s...", filepath.name)
    # create output path
    raw_thumbpath = filepath.parent / f"{filepath.stem}.raw_thumb.jpeg"
    # fmt: off
    ffmpeg_command = (
        "ffmpeg",
        "-hide_banner", "-loglevel", "warning",
        "-y",
        "-ss", "00:00:00",
        "-i", str(filepath),
        "-frames:v", "1",
        str(raw_thumbpath),
    )
    # fmt: on
    log.debug("ffmpeg command: %s.", " ".join(ffmpeg_command))
    process = await asyncio.create_subprocess_exec(*ffmpeg_command)
    if (
        await process.wait() != 0
        or not raw_thumbpath.exists()
        or raw_thumbpath.stat().st_size == 0
    ):
        log.warning("ffmpeg fast extraction failed, trying frame select fallback...")
        # fmt: off
        fallback_command = (
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-y",
            "-i", str(filepath),
            "-vf", "select=eq(n\\,0)",
            "-frames:v", "1",
            str(raw_thumbpath),
        )
        # fmt: on
        process = await asyncio.create_subprocess_exec(*fallback_command)
        if (
            await process.wait() != 0
            or not raw_thumbpath.exists()
            or raw_thumbpath.stat().st_size == 0
        ):
            log.warning("ffmpeg fallback command failed.")
            return None

    return await process_thumbnail(raw_thumbpath)

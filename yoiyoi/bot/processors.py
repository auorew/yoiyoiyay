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
from PIL import Image, ImageColor, ImageDraw, ImageOps

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
from yoiyoi.bot.senders import send_error, send_reply_md2

# get file size
from yoiyoi.extra.requests import save_file

# settings
from yoiyoi.extra.settings import bot_settings

# extra utilities
from yoiyoi.extra.utils import get_file_chunk, replace_file

# twitter carousel constants
from yoiyoi.services.constants import (
    TWITTER_CAROUSEL_GAP,
    TWITTER_CAROUSEL_MARGIN,
    TWITTER_CAROUSEL_RADIUS,
    TWITTER_CAROUSEL_REF_HEIGHT,
)

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
        await send_reply_md2(update, f"Here's your download links\\: {video_links}\\.")
        return
    for link, size in zip(content.links, content.sizes, strict=False):
        if size > MAX_VIDEO_SIZE:
            await send_error(update, "Sorry, file is *too huge*\\!")
            await send_reply_md2(update, f"[Download link]({link})\\.")
            await send_reply_md2(update, "Trying to get smaller version\\.\\.\\.")
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


def _stitch_images_sync(
    image_paths: list[Path],
    output_path: Path,
    fill_color: Optional[str] = None,
    border_radius: Optional[float] = None,
    gap: Optional[float] = None,
    frame_margins: Optional[float | list[float] | tuple[float]] = None,
) -> Path:
    """Stitches images horizontally mirroring Twitter gallery carousel styles:
    - Base parameters at Twitter for reference (at 327.35px reference height):
      - height:         327.35px            | TWITTER_CAROUSEL_REF_HEIGHT
      - border-radius:  8px                 | TWITTER_CAROUSEL_RADIUS
      - gap:            4px                 | TWITTER_CAROUSEL_GAP
      - frame margins:  4px (each side)     | TWITTER_CAROUSEL_MARGIN
      - fill:           transparent         |
    - All images are scaled to match the smallest image height.
    - Parameters are scaled proportionally by target_height / TWITTER_CAROUSEL_REF_HEIGHT.
    - Each image card gets rounded corners.
    """
    if not image_paths:
        raise ValueError("No images to stitch.")

    opened_images: list[Image.Image] = []
    try:
        for p in image_paths:
            img = Image.open(p)
            img = ImageOps.exif_transpose(img)
            opened_images.append(img.convert("RGBA"))

        # Determine target height (smallest among all images)
        target_height = min(img.height for img in opened_images)

        # Proportional scaling factor against Twitter's reference height 327.35px
        scale = target_height / TWITTER_CAROUSEL_REF_HEIGHT

        # 1. Resolve Border Radius (default reference: 8px)
        base_radius = (
            border_radius
            if border_radius is not None
            and isinstance(border_radius, (int, float))
            and border_radius >= 0
            else TWITTER_CAROUSEL_RADIUS
        )
        radius = max(0, round(base_radius * scale))

        # 2. Resolve Gap (default reference: 4px)
        base_gap = (
            gap
            if gap is not None and isinstance(gap, (int, float)) and gap >= 0
            else TWITTER_CAROUSEL_GAP
        )
        resolved_gap = max(0, round(base_gap * scale))

        # 3. Resolve Frame Margins (default reference: 4px per side)
        match frame_margins:
            case None:
                m = TWITTER_CAROUSEL_MARGIN * scale
                top = right = bottom = left = m
            case int() | float() as val:
                m = float(val) * scale
                top = right = bottom = left = m
            case [v, h] | (v, h):
                top = bottom = float(v) * scale
                right = left = float(h) * scale
            case [t, r, b, l] | (t, r, b, l):
                top = float(t) * scale
                right = float(r) * scale
                bottom = float(b) * scale
                left = float(l) * scale
            case _:
                m = TWITTER_CAROUSEL_MARGIN * scale
                top = right = bottom = left = m
                # # Let's not throw any error for now
                # if isinstance(frame_margins, (list, tuple)):
                #     raise ValueError(
                #         "frame_margins sequence must have either 2 or 4 elements: "
                #         "[vertical, horizontal] or [top, right, bottom, left]."
                #     )
                # raise TypeError("Invalid type for frame_margins.")

        # Convert margins to final pixel integers
        top_px = max(0, round(top))
        right_px = max(0, round(right))
        bottom_px = max(0, round(bottom))
        left_px = max(0, round(left))

        log.info(
            "Stitching %d images: target_height=%d, scale=%.3f, "
            "margins=(top=%d, right=%d, bottom=%d, left=%d), "
            "gap=%d, radius=%d, fill_color=%r",
            len(opened_images),
            target_height,
            scale,
            top_px,
            right_px,
            bottom_px,
            left_px,
            resolved_gap,
            radius,
            fill_color,
            image_count=len(opened_images),
            target_height=target_height,
            scale=scale,
            top_margin=top_px,
            right_margin=right_px,
            bottom_margin=bottom_px,
            left_margin=left_px,
            gap=resolved_gap,
            radius=radius,
            fill_color=fill_color,
        )

        # Resize each image to target_height preserving aspect ratio
        scaled_images: list[Image.Image] = []
        for img in opened_images:
            if img.height != target_height:
                scaled_w = max(1, round(img.width * (target_height / img.height)))
                resized_img = img.resize(
                    (scaled_w, target_height), Image.Resampling.LANCZOS
                )
            else:
                resized_img = img

            # Apply rounded corners to individual image
            w, h = resized_img.size
            corner_radius = min(radius, w // 2, h // 2)

            if corner_radius > 0:
                # High-resolution supersampled mask for smooth anti-aliased corners
                ss = 4
                mask_ss = Image.new("L", (w * ss, h * ss), 0)
                draw_ss = ImageDraw.Draw(mask_ss)
                draw_ss.rounded_rectangle(
                    (0, 0, w * ss, h * ss), radius=corner_radius * ss, fill=255
                )
                mask = mask_ss.resize((w, h), Image.Resampling.LANCZOS)

                # Apply mask to image alpha channel
                card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                card.paste(resized_img, (0, 0), mask=mask)
                scaled_images.append(card)
            else:
                scaled_images.append(resized_img)

        # Calculate canvas dimensions using asymmetric margins
        total_width = (
            left_px
            + right_px
            + sum(img.width for img in scaled_images)
            + (len(scaled_images) - 1) * resolved_gap
        )
        total_height = top_px + bottom_px + target_height

        # Determine background color
        if fill_color:
            try:
                rgb = ImageColor.getrgb(fill_color)
                bg_color = (rgb[0], rgb[1], rgb[2], 255)
            except ValueError:
                log.warning(
                    "Invalid fill color %r, defaulting to transparent.", fill_color
                )
                bg_color = (0, 0, 0, 0)
        else:
            bg_color = (0, 0, 0, 0)

        canvas = Image.new("RGBA", (total_width, total_height), bg_color)

        # Paste images onto canvas using custom left and top offsets
        curr_x = left_px
        for img in scaled_images:
            canvas.alpha_composite(img, (curr_x, top_px))
            curr_x += img.width + resolved_gap

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG")
        log.info(
            "Saved stitched canvas: %s (dimensions: %dx%d, size: %d bytes)",
            output_path.name,
            total_width,
            total_height,
            output_path.stat().st_size,
            output_file=output_path.name,
            canvas_width=total_width,
            canvas_height=total_height,
            file_size=output_path.stat().st_size,
        )
        return output_path

    finally:
        for img in opened_images:
            img.close()


async def stitch_images(
    image_paths: list[Path],
    output_path: Path,
    fill_color: Optional[str] = None,
    border_radius: Optional[float] = None,
    gap: Optional[float] = None,
    frame_margins: Optional[float | list[float] | tuple[float]] = None,
) -> Path:
    """Async wrapper to stitch images with customizable layout parameters."""
    return await asyncio.to_thread(
        _stitch_images_sync,
        image_paths=image_paths,
        output_path=output_path,
        fill_color=fill_color,
        border_radius=border_radius,
        gap=gap,
        frame_margins=frame_margins,
    )

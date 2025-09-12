from typing import AsyncGenerator, Optional
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import subprocess
from tempfile import _TemporaryFileWrapper, NamedTemporaryFile
import shutil

# web application
from fastapi import UploadFile

# cache dir
from yoiyoi.app import IM_FMT, IM_MAX, SUCCESS, VI_FMT
from yoiyoi.bot import CACHE_DIR

# working with image with minimal memory
import pyvips

# working with image
from PIL import Image

# structured logging
import structlog

# get logger
log = structlog.get_logger(__name__)


@asynccontextmanager
async def request_space() -> AsyncGenerator[tuple[Path, str], None]:
    unique_id = uuid.uuid4().hex
    folder = CACHE_DIR / unique_id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        yield folder, unique_id
    finally:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)


async def resize_image_file(file: Path, ext: str = "image/jpeg") -> tuple[Path, str, Optional[str]]:
    image = pyvips.Image.new_from_file(
        str(file),
        access="sequential",
    )

    width, height = image.width, image.height
    file_size = file.stat().st_size

    if (width + height) > 10000 or file_size > (1 << 20):  # >1MB
        scale = min(IM_MAX[0] / width, IM_MAX[1] / height, 1.0)
        if scale < 1.0:
            image = image.resize(scale, kernel="lanczos3")

        out_file = file.with_suffix(".jxl")
        image.write_to_file(str(out_file), Q=90)
        send_type = "image/jxl"
    else:
        out_file = file
        send_type = ext

    return out_file, send_type


async def convert_video_file(input_file: Path, output_file: _TemporaryFileWrapper):
    try:
        # fmt: off
        ffmpeg_command = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-i", input_file.name,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "copy",
            "-f", "mp4",
            "-y",
            output_file.name,
        ]
        # fmt: on
        print("Convert: ffmpeg command: %s.", " ".join(ffmpeg_command))
        process = subprocess.run(ffmpeg_command, capture_output=True)
        if process.stderr:
            exc_info = process.stderr.decode("utf-8")
            print(f"Error: {exc_info}")
            return {"message": f"Conversion failed: {exc_info}."}
        else:
            print("Convert: finished.")
            print("File created: %r." % output_file.name)
            return {"message": SUCCESS}
    except Exception as exception:
        exc_info = (
            "Failed to run file command because of "
            f"{exception.__class__.__name__}: {exception!r}."
        )
        print(exc_info)
        return {"message": exc_info}


async def convert_media_file(media_file: Path, ext: str = "any") -> tuple[Path, str, Optional[str]]:
    send_type = ext
    if ext.split("/")[1] in VI_FMT:
        output_file = media_file.with_suffix('.mp4')
        with NamedTemporaryFile() as temp_output_file:
            result = await convert_media_file(media_file, temp_output_file)
            if result["message"] != SUCCESS:
                return media_file, send_type, result["message"]
            temp_output_file.seek(0)
            output_file.write_bytes(temp_output_file.read())
            send_type = "video/mp4"
            return output_file, send_type, None
    elif ext.split("/")[1] in IM_FMT:
        return await resize_image_file(media_file, ext)

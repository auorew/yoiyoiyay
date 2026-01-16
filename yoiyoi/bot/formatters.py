"""Bot formatters"""

import asyncio
import re
import subprocess
import sys

from functools import partial
from pathlib import Path
from typing import AsyncGenerator

# file extension check
import magic

# parse json
import orjson

# structured logging
import structlog

# telegram core bot api
from telegram import Update

# escape markdown
from telegram.helpers import escape_markdown

# pixiv parse states
from yoiyoi.bot import PixivParse

# link types and other info
from yoiyoi.services.constants import LINKS

# Link namedtuple
from yoiyoi.services.namedtuples import Link

# escaping markdown v2
esc = partial(escape_markdown, version=2)

# get logger
log = structlog.get_logger(__name__)

# pixiv regex
pixiv_number = re.compile(r"((?P<n1>\d+)(?:-(?P<n2>\d+))?)")

# octet-stream
NO_EXT = "octet-stream"


async def unescape_html(text: str) -> str:
    """Unescape html escapes (mainly for markdown)

    Args:
        text (str): text with html escapes

    Returns:
        str: text wuthout escapes
    """
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


async def pixiv_parse(
    text: str,
    count: int,
    max_amount: int = 10,
) -> tuple[int, tuple[int]]:
    if not (text and count):
        return (PixivParse.NO_INFO, [])
    ids = []
    for number in re.finditer(pixiv_number, text):
        n1 = int(number.group("n1"))
        if n2 := number.group("n2"):
            n2 = int(n2)
        else:
            n2 = n1
        if n1 > n2:
            ids += reversed(range(n2, n1 + 1))
        else:
            ids += range(n1, n2 + 1)
    ids = list(dict.fromkeys(ids))  # can't use set() because of order
    # check if all numbers within range
    if max(ids) > count or min(ids) < 1:
        log.error("Pixiv Parse: Not within range: [1-%d].", count)
        return (
            PixivParse.NOT_WITHIN_RANGE,
            tuple(filter(lambda x: 1 <= x <= count, ids))[:max_amount],
        )
    # check if there's more than 10 numbers
    if len(ids) > max_amount:
        log.error("Pixiv Parse: Can't choose more than %d files.", max_amount)
        return (PixivParse.OUT_OF_RANGE, tuple(ids[:max_amount]))
    # else everything is fine
    log.debug("Pixiv Parse: Chosen artworks: %r.", ids)
    return (PixivParse.SUCCESS, tuple(ids))


async def formatter(query: str) -> AsyncGenerator[Link, None]:
    """Exctracts links from text and formats them

    Args:
        query (str): text

    Returns:
        AsyncGenerator[Link, None]: async generator of Links
    """
    if not query:
        return
    for re_key, re_type in LINKS.items():
        for link in re.finditer(re_type["re"], query):
            # dictionary keys = format args
            matched = link.groupdict()
            if re_type["link"]:
                _link = re_type["link"].format(**matched)
            else:
                _link = query
            log.debug("Received %s link: %r.", re_key, _link)
            # add to response list
            yield Link(
                re_type["type"],
                _link,
                link["id"],
                link["illust"] if matched.get("illust") else None,
                link["info"] if matched.get("info") else None,
            )


async def get_text(update: Update) -> str:
    """Gets all the text of the message

    Args:
        update (Update): current update

    Returns:
        str: _description_
    """
    mes = update.effective_message
    return "|".join(
        text
        for text in [mes.text, mes.caption]
        + [entity.url for entity in mes.entities + mes.caption_entities]
        if text
    )


async def get_video_info(filepath: str | Path) -> tuple[int, int, int]:
    # try ffprobe
    try:
        log.debug("Get video info: trying ffprobe...")
        # fmt: off
        ffprobe_command = [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "stream=width,height,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            "-select_streams", "v:0",
            str(filepath),
        ]
        # fmt: on
        log.debug("Get video info: ffprobe command: %s.", " ".join(ffprobe_command))
        process = await asyncio.create_subprocess_exec(
            *ffprobe_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if await process.wait() != 0:
            raise Exception("process exited with non-zero value")
        if stderr := await process.stderr.read():
            raise Exception(stderr.decode("utf-8"))
        if not (json_info := orjson.loads(await process.stdout.read())):
            raise Exception("No parseable output")
        size_info = json_info.get("streams", [])
        format_info = json_info.get("format", {})
        if len(size_info) > 0:
            video_info = size_info[0]
            width = video_info.get("width", 0)
            height = video_info.get("height", 0)
            duration = int(float(video_info.get("duration", 0)))
        if not duration:
            duration = int(float(format_info.get("duration", 0)))
        log.info("Get video info: %d x %d, %ds...", width, height, duration)
        return width, height, duration
    except Exception as exception:
        log.warning(
            "Get video info: failed to run ffprobe command because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            filepath=filepath,
        )
    # else
    return 0, 0, 0


def extract_file_name(link_type: str, link: str) -> str:
    """Gets file name from link depending on link type

    Args:
        link_type (str): type of link
        link (str): file URL

    Returns:
        str: file name
    """
    if link_type not in LINKS or "file" not in LINKS[link_type]:
        return link.split("/")[-1].split("?")[0]
    if matched := re.search(LINKS[link_type]["file"], link):
        return matched["id"]


def extract_file_ext_from_bytes(file: bytes):
    # try magic
    try:
        log.debug("Extract ext: trying libmagic...")
        if mime_type := magic.from_buffer(file, mime=True).split("/")[-1]:
            if mime_type != NO_EXT:
                log.info("Extract ext: extension: %s...", mime_type)
                return mime_type
    except Exception as exception:
        log.warning(
            "Failed to run file command because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            file=file[:1024],
        )
    # try linux file command
    try:
        if sys.platform.startswith("linux"):
            log.debug("Extract ext: trying file command...")
            file_command = ["file", "--mime-type", "-"]
            log.debug("Extract ext: file command: %s.", " ".join(file_command))
            process = subprocess.Popen(
                file_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate(input=file)
            if stderr:
                log.warning(f"Error: {stderr.decode('utf-8')}")
            else:
                format_info = stdout.decode("utf-8")
                mime_type = format_info.strip().split(": ")[1].split("/")[-1]
                if mime_type != NO_EXT:
                    log.info("Extract ext: extension: %s...", mime_type)
                return mime_type
    except Exception as exception:
        log.warning(
            "Failed to run file command because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            file=file[:1024],
        )
    # else
    log.info("Extract ext: couldn't get extension. Defaulting to %s.", NO_EXT)
    return NO_EXT


def extract_file_ext(file: Path | str | bytes) -> str:
    if isinstance(file, bytes):
        return extract_file_ext_from_bytes(file)
    if not (isinstance(file, str | Path)):
        return
    # try magic
    try:
        log.debug("Extract ext: trying libmagic...")
        if magic_output := magic.from_file(file, mime=True):
            mime_type = magic_output.split("/")[-1]
            if mime_type != NO_EXT:
                log.info("Extract ext: extension: %s...", mime_type)
                return mime_type
    except Exception as exception:
        log.warning(
            "Failed to run file command because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            file=file,
        )
    # try linux file command
    try:
        if sys.platform.startswith("linux"):
            log.debug("Extract ext: trying file command...")
            file_command = ["file", "--mime-type", file]
            log.debug("Extract ext: file command: %s.", " ".join(file_command))
            output = subprocess.run(file_command, capture_output=True)
            if output.stderr:
                log.warning(f"Error: {output.stderr.decode('utf-8')}")
            else:
                format_info = output.stdout.decode("utf-8")
                mime_type = format_info.strip().split(": ")[1].split("/")[-1]
                if mime_type != NO_EXT:
                    log.info("Extract ext: extension: %s...", mime_type)
                    return mime_type
    except Exception as exception:
        log.warning(
            "Failed to run file command because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            file=file,
        )
    # try ffprobe
    try:
        log.debug("Extract ext: trying ffprobe...")
        # fmt: off
        ffprobe_command = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file
        ]
        # fmt: on
        log.debug("Extract ext: ffprobe command: %s.", " ".join(ffprobe_command))
        output = subprocess.run(ffprobe_command, capture_output=True)
        if output.stderr:
            log.warning(f"Error: {output.stderr.decode('utf-8')}")
        else:
            if format_info := orjson.loads(output.stdout):
                mime_type = format_info["format"]["format_name"].split(",")[0]
                if mime_type != NO_EXT:
                    log.info("Extract ext: extension: %s...", mime_type)
                    return mime_type
    except Exception as exception:
        log.warning(
            "Failed to run file command because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            file=file,
        )
    # else
    log.info("Extract ext: couldn't get extension. Defaulting to %s.", NO_EXT)
    return NO_EXT


async def make_file_name(link_type: str, link: str, file: str | bytes) -> str:
    """Gets file name from file and link depending on link type

    Args:
        link_type (str): type of link
        link (str): file URL
        file (bytes): pathfile or first 1024 bytes of file

    Returns:
        str: new file name
    """
    if link_type is None:
        log.error("Link type is None!")
        return ""
    name = extract_file_name(link_type, link)
    ext = extract_file_ext(file)
    if not name:
        name = f"{link_type}_{int(asyncio.get_event_loop().time())}"

    return ".".join((name, ext))


async def join_file_name(file_name: str, file: str | bytes) -> str:
    """Make file name from file name and extenstion depending on file type

    Args:
        file_name (str): filename
        file (bytes): pathfile or first 1024 bytes of file

    Returns:
        str: new file name
    """
    return ".".join((file_name, extract_file_ext(file)))


async def make_thumb_name(file_name: str, file: str | bytes) -> str:
    return ".".join((file_name.rsplit(".")[0], "thumb", extract_file_ext(file)))

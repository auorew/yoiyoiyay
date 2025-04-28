"""Bot Functions"""

import asyncio
import logging

from pathlib import Path
from typing import Optional

# pyrogram enums
from pyrogram.enums.parse_mode import ParseMode as PM

# pyrogram types
from pyrogram.types import InputMediaDocument, InputMediaPhoto, InputMediaVideo

# telegram core bot api
from telegram import Update

# telegram constants
from telegram.constants import MessageLimit as ML

# telegram errors
from telegram.error import BadRequest

# telegram core bot api extension
from telegram.ext import ContextTypes

# link types and other info
from yoiyoi.api import LinkType, TikTokMediaKind

# instagram api
from yoiyoi.api.instagram import get_instagram_links

# Link, PixivContent, TweetContent namedtuples
from yoiyoi.api.namedtuples import (
    Link,
    PixivContent,
    PixivMedia,
    TikTokMedia,
    TikTokPhoto,
    TikTokVideo,
    TweetContent,
    TweetMedia,
    YouTubeShortMedia,
)

# pixiv api
from yoiyoi.api.pixiv import get_pixiv_links

# tiktok api
from yoiyoi.api.tiktok import get_tiktok_links

# twitter api
from yoiyoi.api.twitter import get_twitter_links

# youtube api
from yoiyoi.api.youtube_short import get_youtube_short_links

# get constants and pyrogram app
from yoiyoi.bot import CACHE_DIR, QUEUE_SIZE, PixivParse

# bot filters
from yoiyoi.bot.filters import clear_context

# bot formatters
from yoiyoi.bot.formatters import (
    esc,
    formatter,
    get_text,
    get_video_info,
    join_file_name,
    make_file_name,
    make_thumb_name,
    pixiv_parse,
)

# bot helpers
from yoiyoi.bot.helpers import notify

# content processor
from yoiyoi.bot.processors import (
    choose_twitter_video,
    convert_image,
    create_thumbnail,
    crop_thumbnail,
    process_image,
    process_video,
)

# bot senders
from yoiyoi.bot.senders import get_message, send_error, send_media_group, send_reply

# database table
from yoiyoi.db.models import Chat

# database helpers
from yoiyoi.db.updaters import update_chat

# get file size
from yoiyoi.extra.request_helpers import (
    FAKE_HEADERS,
    PIXIV_HEADERS,
    get_content_type,
    save_file,
)

# media styles
from yoiyoi.extra.styles import (
    PixivStyle,
    Style,
    TikTokStyle,
    TwitterStyle,
    YouTubeShortStyle,
)

# extra utilities
from yoiyoi.extra.utils import delete_files, move_file

# setup logger
log = logging.getLogger(__name__)

# update queue limiter
update_queue = asyncio.Queue(QUEUE_SIZE)

# current media groups
media_groups = set()

# media type
Media = TweetMedia | PixivMedia | TikTokMedia | YouTubeShortMedia


async def generate_info(link: Link, style: Style, style_id: int, media: Media) -> str:
    info = style.get_format(style_id, media)
    if link.info:
        info = f"{link.info}\n\n{info}"
    if len(info) > ML.CAPTION_LENGTH:
        info = info[: (ML.CAPTION_LENGTH - 6)].rsplit(None, 1)[0] + "..."
    return info


async def get_info(link: Link, style: Style, chat: Chat, media: Media) -> Optional[str]:
    if chat.include_link:
        return await generate_info(link, style, getattr(chat, style.field), media)


async def send_collection(
    update: Update,
    chat: Chat,
    storage: set,
    files: list,
    docs: list = None,
):
    try:
        message = await get_message(update)
        quoted = not chat.delete_link
        i, j = 0, 10
        while i < len(files):
            # send media group
            log.info("Sending media group...")
            if post := await send_media_group(message, media=files[i:j], quote=quoted):
                log.info("Sent media group.")
            # send document group
            if docs and post:
                log.info("Sending document group...")
                if await send_media_group(post[0], media=docs[i:j], quote=True):
                    log.info("Sent document group.")
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
        Path(CACHE_DIR / str(update.update_id)).rmdir()


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
    error_text = f"[*This twitter content*]({link.link}) "
    log.info("Twitter Link: %s.", link.link)
    # get media
    if (tweet := await get_twitter_links(link.id)) and (count := len(tweet.content)):
        info = await get_info(link, TwitterStyle, chat, tweet)
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        ids = tuple(range(1, count + 1))
        parsed_ids = await pixiv_parse(link.illust, count)
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
        for idx in ids:
            media: TweetContent = tweet.content[idx - 1]
            if media.type == "photo":
                filepath = await save_file(media.links[0])
                filename = await make_file_name("twitter", media.links[0], filepath)
                filepath = move_file(filepath, storage_folder / filename)
                storage.add(filepath)
                log.debug("Filename: %r.", filename)
                if not (imagepath := await process_image(filepath)):
                    log.error("Couldn't resize image.")
                    await send_error(
                        update,
                        error_text + "contains images the bot couldn't resize\\!",
                        quote=not chat.delete_link,
                    )
                    return
                if (imagepath := Path(imagepath)) != filepath:
                    imagepath = move_file(imagepath, storage_folder / f"RE_{filename}")
                    storage.add(imagepath)
                # add to collection
                files.append(
                    InputMediaPhoto(
                        media=imagepath,
                        caption=info if idx == ids[0] else None,
                        parse_mode=PM.HTML,
                    )
                )
                if chat.tw_orig:
                    docs.append(
                        InputMediaDocument(
                            media=filepath,
                            parse_mode=PM.HTML,
                        )
                    )
            else:
                if not (videolink := await choose_twitter_video(update, media)):
                    log.error("Couldn't get links.")
                    await send_error(
                        update,
                        error_text + "contains videos the bot couldn't send\\!",
                        quote=not chat.delete_link,
                    )
                    return
                filepath = await save_file(videolink)
                filename = await make_file_name("twitter", videolink, filepath)
                filepath = move_file(filepath, storage_folder / filename)
                storage.add(filepath)
                if not (videopath := await process_video(filepath)):
                    log.error("Couldn't add sound to video.")
                    await send_error(
                        update,
                        error_text + "contains videos the bot couldn't send\\!",
                        quote=not chat.delete_link,
                    )
                    return
                if videopath != filepath:
                    storage.add(videopath)
                videoinfo = await get_video_info(videopath)
                thumbpath = await save_file(media.thumb)
                thumbname = await make_thumb_name(filename, thumbpath)
                thumbpath = move_file(thumbpath, storage_folder / thumbname)
                storage.add(thumbpath)
                # add to collection
                files.append(
                    InputMediaVideo(
                        media=videopath,
                        thumb=thumbpath,
                        caption=info if idx == ids[0] else None,
                        parse_mode=PM.HTML,
                        width=videoinfo[0],
                        height=videoinfo[1],
                        duration=videoinfo[2],
                    )
                )
        log.debug("Finished adding to collection.")
        log.debug("Caption: %r.", info)
        if await send_collection(update, chat, storage, files, docs):
            return
    # if no links returned
    log.error("Couldn't get twitter content.")
    await send_error(
        update,
        error_text
        + (
            "can't be found or downloaded\\. "
            "If this seems to be wrong, try again later\\."
        ),
        quote=not chat.delete_link,
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
    error_text = f"[*This instagram content*]({link.link}) "
    log.info("Instagram Link: %s.", link.link)
    # get media
    if media := await get_instagram_links(link.link):
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        info = media[0].source if chat.include_link else None
        for idx, item in enumerate(media):
            filepath = await save_file(item.link)
            if not (filename := item.name):
                filename = await make_file_name("instagram", item.link, filepath)
            else:
                filename = await join_file_name(filename, filepath)
            filepath = move_file(filepath, storage_folder / filename)
            storage.add(filepath)
            log.debug("Filename: %r.", filename)
            if item.type == "image":
                if not (imagepath := await process_image(filepath)):
                    log.error("Couldn't resize image.")
                    await send_error(
                        update,
                        error_text + "contains images the bot couldn't resize\\!",
                        quote=not chat.delete_link,
                    )
                    return
                if (imagepath := Path(imagepath)) != filepath:
                    imagepath = move_file(imagepath, storage_folder / f"RE_{filename}")
                    storage.add(imagepath)
                files.append(
                    InputMediaPhoto(
                        media=imagepath,
                        caption=info if not idx else None,
                        parse_mode=PM.HTML,
                    )
                )
                if chat.in_orig:
                    docs.append(
                        InputMediaDocument(
                            media=filepath,
                            parse_mode=PM.HTML,
                        )
                    )
            if item.type == "video":
                videoinfo = await get_video_info(filepath)
                thumbpath = await save_file(item.thumb)
                thumbname = await make_thumb_name(filename, thumbpath)
                thumbpath = move_file(thumbpath, storage_folder / thumbname)
                storage.add(thumbpath)
                files.append(
                    InputMediaVideo(
                        media=filepath,
                        thumb=thumbpath,
                        caption=info if not idx else None,
                        parse_mode=PM.HTML,
                        width=videoinfo[0],
                        height=videoinfo[1],
                        duration=videoinfo[2],
                    )
                )
        log.debug("Finished adding to collection.")
        log.debug("Caption: %r.", info)
        if await send_collection(update, chat, storage, files, docs):
            return
    # if no links returned
    log.error("Couldn't get instagram content.")
    await send_error(
        update,
        error_text
        + (
            "can't be found or downloaded\\. "
            "If this seems to be wrong, try again later\\."
        ),
        quote=not chat.delete_link,
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
    error_text = f"[*This tiktok content*]({link.link}) "
    log.info("TikTok Link: %s.", link.link)
    # get media
    if media := await get_tiktok_links(link.link):
        info = await get_info(link, TikTokStyle, chat, media)
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        if media.kind == TikTokMediaKind.SLIDESHOW and chat.tt_slide_mode == 1:
            photos = list(filter(lambda x: isinstance(x, TikTokPhoto), media.content))
            i, j = 0, 10
            while i < len(photos):
                for idx, media_photo in enumerate(photos[i:j], i):
                    filelink = media_photo.link
                    filepath = await save_file(filelink)
                    if not (filename := media_photo.name):
                        filename = await make_file_name("tiktok", filelink, filepath)
                    else:
                        filename = await join_file_name(filename, filepath)
                    filepath = move_file(filepath, storage_folder / filename)
                    storage.add(filepath)
                    log.debug("Filename: %r.", filename)
                    if not (imagepath := await process_image(filepath)):
                        log.error("Couldn't resize image.")
                        await send_error(
                            update,
                            error_text + "contains images the bot couldn't resize\\!",
                            quote=not chat.delete_link,
                        )
                        return
                    if (imagepath := Path(imagepath)) != filepath:
                        filename = await join_file_name(filename, filepath)
                        imagepath = move_file(
                            imagepath, storage_folder / f"RE_{filename}"
                        )
                        storage.add(imagepath)
                    files.append(
                        InputMediaPhoto(
                            media=imagepath,
                            caption=info if idx == i else None,
                            parse_mode=PM.HTML,
                        )
                    )
                    if chat.tt_orig:
                        docs.append(
                            InputMediaDocument(
                                media=filepath,
                                parse_mode=PM.HTML,
                            )
                        )
                # get next 10 photos/docs
                i, j = j, j + 10
        else:
            videos = list(filter(lambda x: isinstance(x, TikTokVideo), media.content))
            # check size
            filepath = None
            if not videos:
                if media.kind == TikTokMediaKind.SLIDESHOW:
                    error_text += (
                        "can't be sent, because didn't find rendered video\\! "
                        "Consider changing TikTok mode to slideshow mode with "
                        "/tiktok\\_mode command\\."
                    )
                    log.error("Can's send as video.")
                else:
                    error_text += "can't be sent, because didn't find any video\\!"
                    log.error("Can's send as video.")
            else:
                for vid in videos:
                    if 0 < vid.size < 50 << 20:
                        filepath = await save_file(vid.link, "GET", **vid.extra)
                        break
                else:
                    # if file is too big
                    error_text += "can't be sent, because video file is too big\\!"
                    log.error("Video file is too big.")
            # upload video if any
            if filepath:
                filename = await join_file_name(str(media.id), filepath)
                videopath = move_file(filepath, storage_folder / filename)
                storage.add(videopath)
                videoinfo = await get_video_info(videopath)
                thumbpath = await save_file(media.thumb)
                thumbname = await make_thumb_name(filename, thumbpath)
                thumbpath = move_file(thumbpath, storage_folder / thumbname)
                storage.add(thumbpath)
                files.append(
                    InputMediaVideo(
                        media=videopath,
                        thumb=thumbpath,
                        caption=info,
                        parse_mode=PM.HTML,
                        width=videoinfo[0],
                        height=videoinfo[1],
                        duration=videoinfo[2],
                    )
                )
        if files:
            log.debug("Finished adding to collection.")
            log.debug("Caption: %r.", info)
            if await send_collection(update, chat, storage, files, docs):
                return
    # if there is no video
    else:
        log.error("Couldn't get tiktok content.")
        error_text += (
            "can't be found or downloaded\\! If this seems to be wrong, try "
            "again later\\."
        )
    await send_error(
        update,
        error_text,
        quote=not chat.delete_link,
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
    error_text = f"[*This youtube content*]({link.link}) "
    log.info("YouTube Short Link: %s.", link.link)
    # get media
    if video := await get_youtube_short_links(link):
        info = await get_info(link, YouTubeShortStyle, chat, video)
        files, storage = [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        filepath = None
        for vid in video.content:
            if 0 < vid.size < 50 << 20:
                filepath = await save_file(vid.link)
                break
        else:
            # if file is too big
            error_text += "can't be sent, because video file is too big\\!"
            log.error("Video file is too big.")
        # upload video if any
        if filepath:
            filename = await join_file_name(video.id, filepath)
            videopath = move_file(filepath, storage_folder / filename)
            storage.add(videopath)
            videoinfo = await get_video_info(videopath)
            thumbpath = await save_file(video.thumb)
            thumbname = await make_thumb_name(filename, thumbpath)
            thumbpath = move_file(thumbpath, storage_folder / thumbname)
            if await crop_thumbnail(thumbpath, videoinfo[0], videoinfo[1]):
                log.info("Successfully cropped thumbnail.")
            storage.add(thumbpath)
            files.append(
                InputMediaVideo(
                    media=videopath,
                    thumb=thumbpath,
                    caption=info,
                    parse_mode=PM.HTML,
                    width=videoinfo[0],
                    height=videoinfo[1],
                    duration=videoinfo[2],
                )
            )
            log.debug("Finished adding to collection.")
            log.debug("Caption: %r.", info)
            if await send_collection(update, chat, storage, files):
                return
    # if there is no video
    log.error("Couldn't get youtube short content.")
    error_text += (
        "can't be found or downloaded\\! If this seems to be wrong, try " "again later\\."
    )
    await send_error(
        update,
        error_text,
        quote=not chat.delete_link,
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
    error_text = f"[*This pixiv content*]({link.link}) "
    log.info("Pixiv Link: %s.", link.link)
    # get media
    if (art := await get_pixiv_links(link.id)) and (count := len(art.content)):
        info = await get_info(link, PixivStyle, chat, art)
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        ids = [1]
        parsed_ids = await pixiv_parse(link.illust, count)
        if art.type == "ugoira":
            media: PixivContent = art.content[0]
            filepath = await save_file(
                media.original,
                headers={
                    **FAKE_HEADERS,
                    "Range": "bytes=0-",
                    "Referer": "https://t-hk.ugoira.com/",
                },
            )
            filename = await make_file_name("pixiv", media.original, filepath)
            filepath = move_file(filepath, storage_folder / filename)
            storage.add(filepath)
            if not (videopath := await process_video(filepath)):
                log.error("Couldn't add sound to video.")
                await send_error(
                    update,
                    error_text + "contains videos the bot couldn't send\\!",
                    quote=not chat.delete_link,
                )
                return
            if videopath != filepath:
                storage.add(videopath)
            videoinfo = await get_video_info(videopath)
            thumbpath = await save_file(media.thumb, headers=PIXIV_HEADERS)
            thumbname = await make_thumb_name(filename, thumbpath)
            thumbpath = move_file(thumbpath, storage_folder / thumbname)
            storage.add(thumbpath)
            # add to collection
            files.append(
                InputMediaVideo(
                    media=videopath,
                    thumb=thumbpath,
                    caption=info,
                    parse_mode=PM.HTML,
                    width=videoinfo[0],
                    height=videoinfo[1],
                    duration=videoinfo[2],
                )
            )
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
                    filename = await make_file_name("pixiv", filelink, filepath)
                    filepath = move_file(filepath, storage_folder / filename)
                    storage.add(filepath)
                    log.debug("Filename: %r.", filename)
                    if not (imagepath := await process_image(filepath)):
                        log.error("Couldn't resize image.")
                        await send_error(
                            update,
                            error_text + "contains images the bot couldn't resize\\!",
                            quote=not chat.delete_link,
                        )
                        return
                    if (imagepath := Path(imagepath)) != filepath:
                        imagepath = move_file(
                            imagepath, storage_folder / f"RE_{filename}"
                        )
                        storage.add(imagepath)
                    files.append(
                        InputMediaPhoto(
                            media=imagepath,
                            caption=info if ids[i] == idx else None,
                            parse_mode=PM.HTML,
                        )
                    )
                    if chat.px_orig:
                        docs.append(
                            InputMediaDocument(
                                media=filepath,
                                parse_mode=PM.HTML,
                            )
                        )
                # get next 10 photos/docs
                i, j = j, j + 10
        if files:
            log.debug("Finished adding to collection.")
            log.debug("Caption: %r.", info)
            if await send_collection(update, chat, storage, files, docs):
                return
    else:
        log.error("Couldn't get pixiv content.")
        error_text += (
            "can't be found or downloaded\\. If this seems to be wrong, try "
            "again later\\."
        )
    await send_error(
        update,
        error_text,
        quote=not chat.delete_link,
    )


async def send_discord(
    update: Update,
    link: Link,
    chat: Chat,
) -> None:
    """Sends discord media

    Args:
        update (Update): current update
        link (Link): discord media link
        chat (Chat): current chat
    """
    error_text = f"[*This discord content*]({link.link}) "
    log.info("Discord Link: %s.", link.link)
    # get media
    files, storage = [], set()
    storage_folder = Path(CACHE_DIR / str(update.update_id))
    storage_folder.mkdir(parents=True, exist_ok=True)

    info = link.link
    content_type = await get_content_type(link.link, method="GET")
    if content_type != "text/plain":
        filepath = await save_file(link.link)
        tempname = await make_file_name("discord", link.link, filepath)
        filename = f"{tempname.split('.')[0]}.{tempname.split('.')[-1]}"
        filepath = move_file(filepath, storage_folder / filename)
        storage.add(filepath)
        if content_type.split("/")[0] == "video":
            thumbpath = await create_thumbnail(filepath)
            storage.add(thumbpath)
            videoinfo = await get_video_info(filepath)
            if videopath := await process_video(filepath):
                files.append(
                    InputMediaVideo(
                        media=videopath,
                        thumb=thumbpath,
                        caption=info,
                        parse_mode=PM.DISABLED,
                        width=videoinfo[0],
                        height=videoinfo[1],
                        duration=videoinfo[2],
                    )
                )
        else:
            if imagepath := await convert_image(filepath):
                if (imagepath := Path(imagepath)) != filepath:
                    imagepath = move_file(
                        imagepath, storage_folder / f"RE_{filepath.stem}.png"
                    )
                    storage.add(imagepath)
                files.append(
                    InputMediaPhoto(
                        media=imagepath,
                        caption=info,
                        parse_mode=PM.DISABLED,
                    )
                )
        log.debug("Finished adding to collection.")
        log.debug("Caption: %r.", info)
        if await send_collection(update, chat, storage, files):
            return
    else:
        error_text += (
            "can't be found or downloaded, because it\\'s no longer available\\."
        )

        # files.append(
        #     InputMediaVideo(
        #         media=videopath,
        #         thumb=thumbpath,
        #         caption=info,
        #         parse_mode=PM.HTML,
        #         width=videoinfo[0],
        #         height=videoinfo[1],
        #         duration=videoinfo[2],
        #     )
        # )

    # else:
    #     log.error("Couldn't get pixiv content.")

    # await send_error(
    #     update,
    #     error_text,
    #     quote=not chat.delete_link,
    # )


@clear_context()
async def process_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Answers to user's links

    Args:
        update (Update): current update
        _ (ContextTypes): current context
    """
    notify(update, function="process_link")
    # get current chat
    chat = await update_chat(update.effective_chat)
    # check if message is forwarded and if chat should ignore it
    if update.effective_message.forward_origin and chat.ignore_fw:
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
            log.debug("Received text: %r.", text)
            async for link in formatter(text):
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
                    case LinkType.DISCORD:
                        await send_discord(update, link, chat)
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

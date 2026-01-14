"""Bot Functions"""

import asyncio
import gc
import tracemalloc

from pathlib import Path

# structured logging
import structlog

# contextvars
from structlog.contextvars import unbind_contextvars

# telegram core bot api
from telegram import InputMediaDocument, InputMediaPhoto, InputMediaVideo, Update

# telegram constants
from telegram.constants import ParseMode as PM

# telegram errors
from telegram.error import BadRequest

# telegram core bot api extension
from telegram.ext import ContextTypes

# get constants
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
from yoiyoi.bot.helpers import get_info, notify

# content processor
from yoiyoi.bot.processors import (
    convert_image,
    create_thumbnail,
    crop_thumbnail,
    process_image,
    process_video,
)

# bot senders
from yoiyoi.bot.senders import reply_media_group, send_error, send_reply

# database table
from yoiyoi.db.models import Chat

# database helpers
from yoiyoi.db.updaters import update_chat

# request helpers
from yoiyoi.extra.request_helpers import PIXIV_HEADERS, get_fake_headers

# get file size
from yoiyoi.extra.requests import get_content_type, save_file

# media styles
from yoiyoi.extra.styles import (
    PixivStyle,
    XiaohongshuStyle,
    YouTubeShortStyle,
)

# collect memory stats
from yoiyoi.extra.tracemalloc_helpers import display_top

# extra utilities
from yoiyoi.extra.utils import delete_files, move_file

# link types and other info
from yoiyoi.services.constants import LinkType

# instagram api
from yoiyoi.services.instagram.api import get_instagram_links

# Link, PixivContent, TweetContent namedtuples
from yoiyoi.services.namedtuples import (
    Link,
    PixivContent,
    XiaohongshuVideo,
)

# pixiv api
from yoiyoi.services.pixiv.api import get_pixiv_links

# tiktok api
from yoiyoi.services.registry import TikTokSender, TwitterSender

# xiaohongshu api
from yoiyoi.services.xiaohongshu.api import get_xiaohongshu_links

# youtube api
from yoiyoi.services.youtube_short.api import get_youtube_short_links

# setup logger
log = structlog.get_logger(__name__)

# update queue limiter
update_queue = asyncio.Queue(QUEUE_SIZE)

# current media groups
media_groups = set()

# limit number of simultaneous uploads
UPLOAD_SEMAPHORE = asyncio.Semaphore(2)


async def send_collection(
    update: Update,
    chat: Chat,
    storage: set,
    file_handlers: list,
    files: list,
    doc_handlers: list = None,
    docs: list = None,
):
    try:
        # message = await get_message(update)
        message = update.effective_message
        quoted = not chat.delete_link
        i, j = 0, 10
        while i < len(files):
            # send media group
            log.info("Sending media group...")
            if post := await reply_media_group(
                message,
                media=files[i:j],
                do_quote=quoted,
            ):
                log.info("Sent media group.")
            for file_handler in file_handlers[i:j]:
                file_handler.close()
            # send document group
            if docs and doc_handlers and post:
                log.info("Sending document group...")
                if await reply_media_group(
                    post[0],
                    media=docs[i:j],
                    do_quote=True,
                ):
                    log.info("Sent document group.")
                for doc_handler in doc_handlers[i:j]:
                    doc_handler.close()
            # get next 10 photos/docs
            i, j = j, j + 10
        # seems to be successful
        return True
    except Exception as exception:
        log.warning(
            "Failed to send files because of %s: %r.",
            exception.__class__.__name__,
            exception,
            exc_info=True,
            # function info
            chat=chat,
            storage=storage,
            file_handlers=file_handlers,
            files=files,
            doc_handlers=doc_handlers,
            docs=docs,
        )
        return False
    finally:
        # delete all files
        log.debug("Storage: %s.", storage)
        delete_files(storage)
        for file_handler in file_handlers:
            file_handler.close()
        if doc_handlers:
            for doc_handler in doc_handlers:
                doc_handler.close()
        Path(CACHE_DIR / str(update.update_id)).rmdir()


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
    file_handlers, doc_handlers = [], []
    # get media
    if media := await get_instagram_links(link.link):
        files, docs, storage = [], [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        info = media[0].source if chat.include_link else None
        for idx, item in enumerate(media):
            filepath = await save_file(
                item.link,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;"
                    "q=0.8,application/signed-exchange;v=b3;"
                    "q=0.7",
                    "Accept-Language": "en-GB,en;q=0.9",
                    "Cache-Control": "max-age=0",
                    "Dnt": "1",
                    "Priority": "u=0, i",
                    "Sec-Ch-Ua": '"Chromium";'
                    'v="124", "Google Chrome";'
                    'v="124", "Not-A.Brand";'
                    'v="99',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": "macOS",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
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
                        do_quote=not chat.delete_link,
                    )
                    return
                if (imagepath := Path(imagepath)) != filepath:
                    imagepath = move_file(
                        imagepath, storage_folder / f"RE_{filepath.stem}{filepath.suffix}"
                    )
                    storage.add(imagepath)
                # add to collection
                image_handler = imagepath.open("rb")
                file_handlers.append(image_handler)
                files.append(
                    InputMediaPhoto(
                        media=image_handler,
                        caption=info if not idx else None,
                        parse_mode=PM.HTML,
                    )
                )
                if chat.in_orig:
                    doc_handler = filepath.open("rb")
                    doc_handlers.append(doc_handler)
                    docs.append(
                        InputMediaDocument(
                            media=doc_handler,
                            parse_mode=PM.HTML,
                            disable_content_type_detection=True,
                        )
                    )
            if item.type == "video":
                videoinfo = await get_video_info(filepath)
                thumbpath = await save_file(item.thumb)
                thumbname = await make_thumb_name(filename, thumbpath)
                thumbpath = move_file(thumbpath, storage_folder / thumbname)
                storage.add(thumbpath)
                # add to collection
                video_handler = filepath.open("rb")
                file_handlers.append(video_handler)
                files.append(
                    InputMediaVideo(
                        media=video_handler,
                        thumbnail=thumbpath.read_bytes(),
                        caption=info if not idx else None,
                        parse_mode=PM.HTML,
                        width=videoinfo[0],
                        height=videoinfo[1],
                        duration=videoinfo[2],
                    )
                )
        log.debug("Finished adding to collection.")
        log.debug("Caption: %r.", info)
        if await send_collection(
            update,
            chat,
            storage,
            file_handlers,
            files,
            doc_handlers,
            docs,
        ):
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
        do_quote=not chat.delete_link,
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
    file_handlers = []
    # get media
    if video := await get_youtube_short_links(link):
        info = await get_info(link, YouTubeShortStyle, chat, video)
        files, storage = [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        filepath = None
        for vid in video.content:
            if 0 < vid.size < 50 << 20:
                filepath = await save_file(vid.link, headers=vid.headers)
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
            # add to collection
            video_handler = videopath.open("rb")
            file_handlers.append(video_handler)
            files.append(
                InputMediaVideo(
                    media=video_handler,
                    thumbnail=thumbpath.read_bytes(),
                    caption=info,
                    parse_mode=PM.HTML,
                    width=videoinfo[0],
                    height=videoinfo[1],
                    duration=videoinfo[2],
                )
            )
            log.debug("Finished adding to collection.")
            log.debug("Caption: %r.", info)
            if await send_collection(
                update,
                chat,
                storage,
                file_handlers,
                files,
            ):
                return
    # if there is no video
    log.error("Couldn't get youtube short content.")
    error_text += (
        "can't be found or downloaded\\! If this seems to be wrong, try " "again later\\."
    )
    await send_error(
        update,
        error_text,
        do_quote=not chat.delete_link,
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
    file_handlers, doc_handlers = [], []
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
                    **get_fake_headers(),
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
                    do_quote=not chat.delete_link,
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
            video_handler = videopath.open("rb")
            file_handlers.append(video_handler)
            files.append(
                InputMediaVideo(
                    media=video_handler,
                    thumbnail=thumbpath.read_bytes(),
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
                            do_quote=not chat.delete_link,
                        )
                        return
                    if (imagepath := Path(imagepath)) != filepath:
                        imagepath = move_file(
                            imagepath,
                            storage_folder / f"RE_{filepath.stem}{filepath.suffix}",
                        )
                        storage.add(imagepath)
                    # add to collection
                    image_handler = imagepath.open("rb")
                    file_handlers.append(image_handler)
                    files.append(
                        InputMediaPhoto(
                            media=image_handler,
                            caption=info if ids[i] == idx else None,
                            parse_mode=PM.HTML,
                        )
                    )
                    if chat.px_orig:
                        doc_handler = filepath.open("rb")
                        doc_handlers.append(doc_handler)
                        docs.append(
                            InputMediaDocument(
                                media=doc_handler,
                                parse_mode=PM.HTML,
                                disable_content_type_detection=True,
                            )
                        )
                # get next 10 photos/docs
                i, j = j, j + 10
        if files:
            log.debug("Finished adding to collection.")
            log.debug("Caption: %r.", info)
            if await send_collection(
                update,
                chat,
                storage,
                file_handlers,
                files,
                doc_handlers,
                docs,
            ):
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
        do_quote=not chat.delete_link,
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
    file_handlers = []
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
                # add to collection
                video_handler = videopath.open("rb")
                file_handlers.append(video_handler)
                files.append(
                    InputMediaVideo(
                        media=video_handler,
                        thumbnail=thumbpath.read_bytes(),
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
                        imagepath, storage_folder / f"RE_{filepath.stem}{filepath.suffix}"
                    )
                    storage.add(imagepath)
                # add to collection
                image_handler = imagepath.open("rb")
                file_handlers.append(image_handler)
                files.append(
                    InputMediaPhoto(
                        media=image_handler,
                        caption=info,
                        parse_mode=PM.HTML,
                    )
                )
        log.debug("Finished adding to collection.")
        log.debug("Caption: %r.", info)
        if await send_collection(
            update,
            chat,
            storage,
            file_handlers,
            files,
        ):
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
    #     do_quote=not chat.delete_link,
    # )


async def send_xiaohongshu(
    update: Update,
    link: Link,
    chat: Chat,
) -> None:
    """Sends xiaohongshu video

    Args:
        update (Update): current update
        link (Link): xiaohongshu link
        chat (Chat): current chat
    """
    error_text = f"[*This xiaohongshu content*]({link.link}) "
    log.info("Xiaohongshu Link: %s.", link.link)
    file_handlers = []
    # get media
    if media := await get_xiaohongshu_links(link.link):
        info = await get_info(link, XiaohongshuStyle, chat, media)
        files, storage = [], set()
        storage_folder = Path(CACHE_DIR / str(update.update_id))
        storage_folder.mkdir(parents=True, exist_ok=True)
        videos = list(filter(lambda x: isinstance(x, XiaohongshuVideo), media.content))
        # check size
        filepath = None
        if not videos:
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
            thumbpath = await save_file(media.thumb, "GET", **vid.extra)
            thumbname = await make_thumb_name(filename, thumbpath)
            thumbpath = move_file(thumbpath, storage_folder / thumbname)
            storage.add(thumbpath)
            # add to collection
            video_handler = videopath.open("rb")
            file_handlers.append(video_handler)
            files.append(
                InputMediaVideo(
                    media=video_handler,
                    thumbnail=thumbpath.read_bytes(),
                    caption=info,
                    parse_mode=PM.HTML,
                    width=videoinfo[0],
                    height=videoinfo[1],
                    duration=videoinfo[2],
                )
            )
        log.debug("Finished adding to collection.")
        log.debug("Caption: %r.", info)
        if await send_collection(
            update,
            chat,
            storage,
            file_handlers,
            files,
        ):
            return
    # if there is no video
    else:
        log.error("Couldn't get xiaohongshu content.")
        error_text += (
            "can't be found or downloaded\\! If this seems to be wrong, try "
            "again later\\."
        )
    await send_error(
        update,
        error_text,
        do_quote=not chat.delete_link,
    )


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
    snapshot_before = tracemalloc.take_snapshot()

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
        async with UPLOAD_SEMAPHORE:
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
                            await TwitterSender(update, link, chat).run()
                        case LinkType.INSTAGRAM:
                            await send_instagram(update, link, chat)
                        case LinkType.TIKTOK:
                            await TikTokSender(update, link, chat).run()
                        case LinkType.YOUTUBE_SHORT:
                            await send_youtube_short(update, link, chat)
                        case LinkType.PIXIV:
                            await send_pixiv(update, link, chat)
                        case LinkType.DISCORD:
                            await send_discord(update, link, chat)
                        case LinkType.XIAOHONGSHU:
                            await send_xiaohongshu(update, link, chat)
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
        # unbind update_id
        unbind_contextvars("update_id")
        # force garbage collection
        gc.collect()

        snapshot_after = tracemalloc.take_snapshot()
        display_top(snapshot_after, prev_snapshot=snapshot_before)

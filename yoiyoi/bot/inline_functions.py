"""Bot Inline Functions"""

import asyncio
import logging

from typing import Any, AsyncGenerator, Tuple

# async caching
from aiocache import cached

# telegram core bot api
from telegram import (
    Bot,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultVideo,
    InputTextMessageContent,
    Update,
)

# telegram constants
from telegram.constants import ParseMode as PM

# bad request exception
from telegram.error import BadRequest

# telegram core bot api extension
from telegram.ext import ContextTypes

# link types and other info
from yoiyoi.api import LinkType

# instagram api
from yoiyoi.api.instagram import get_instagram_links

# Link namedtuple
from yoiyoi.api.namedtuples import Link

# pixiv api
from yoiyoi.api.pixiv import get_pixiv_links

# tiktok api
from yoiyoi.api.tiktok import get_tiktok_links

# twitter api
from yoiyoi.api.twitter import get_twitter_links

# youtube api
from yoiyoi.api.youtube_short import get_youtube_short_links

# pixiv parse states
from yoiyoi.bot import PixivParse

# bot formatters
from yoiyoi.bot.formatters import formatter, pixiv_parse

# bot helpers
from yoiyoi.bot.helpers import notify

# database table
from yoiyoi.db.models import Chat

# database helpers
from yoiyoi.db.updaters import update_chat

# get file size
from yoiyoi.extra.request_helpers import get_content_size

# settings
from yoiyoi.extra.settings import bot_settings

# media styles
from yoiyoi.extra.styles import PixivStyle, TikTokStyle, TwitterStyle, YouTubeShortStyle

# get logger
log = logging.getLogger(__name__)

InlineVideo = InlineQueryResultVideo | InlineQueryResultArticle
InlineTwitter = (
    InlineQueryResultCachedPhoto | InlineQueryResultVideo | InlineQueryResultArticle
)
InlinePixiv = (
    InlineQueryResultCachedPhoto | InlineQueryResultVideo | InlineQueryResultArticle
)
InlineInstagram = (
    InlineQueryResultCachedPhoto | InlineQueryResultCachedVideo | InlineQueryResultArticle
)

MAX_PIXIV_IMAGES = 5


async def aenumerate(
    async_generator: AsyncGenerator[Any, None],
    start: int = 0,
) -> AsyncGenerator[Tuple[int, Any], None]:
    """Async enumerate

    Args:
        generator (_type_): async generator
        start (int, optional): start value. Defaults to 0.

    Yields:
        _type_: _description_
    """
    index = start
    async for value in async_generator:
        yield index, value
        index += 1


async def create_in_text(id: str, title: str, text: str):
    return InlineQueryResultArticle(
        id=id,
        title=title,
        description=text,
        input_message_content=InputTextMessageContent(text),
    )


@cached(ttl=None)
async def get_cached_media(bot: Bot, kind: str, media_link: str):
    match kind:
        case "photo":
            post = await bot.send_photo(
                chat_id=bot_settings.dump,
                photo=media_link,
            )
            return post.effective_attachment[-1].file_id
        case "video":
            post = await bot.send_video(
                chat_id=bot_settings.dump,
                video=media_link,
            )
            return post.effective_attachment.file_id
        case _:
            return


async def inline_twitter(
    update: Update,
    link: Link,
    data: dict,
    user: Chat,
    bot: Bot,
) -> InlineTwitter:
    """Sends inline twitter media

    Args:
        update (Update): current update
        link (str): tiktok link
        data (dict): inline data
        user (Chat): sender
        bot (Bot): bot to send messages to dump channel

    Returns:
        InlineTwitter: inline query result
    """
    if tweet := await get_twitter_links(link.id):
        results = []
        for index, media in enumerate(tweet.content, 1):
            answer_dict = {
                "id": f"{data['id']}/{index}",
                "title": data["title"].replace(":", f"/{index}:"),
            }
            caption_dict = {
                "description": f"@{tweet.user} : {tweet.desc}",
                "parse_mode": PM.HTML,
                "caption": (
                    TwitterStyle.get_format(user.tw_style, tweet)
                    if user.include_link
                    else None
                ),
            }
            if media.type == "photo":
                for photo_size in media.sizes:
                    if photo_size < 10 << 20:
                        results.append(
                            InlineQueryResultCachedPhoto(
                                **answer_dict,
                                **caption_dict,
                                photo_file_id=await get_cached_media(
                                    bot,
                                    "photo",
                                    media.links[0],
                                ),
                            ),
                        )
                        break
                else:
                    results.append(
                        await create_in_text(
                            **answer_dict,
                            text="Image is too big, send link to bot.",
                        )
                    )
            else:
                for video_size in media.sizes:
                    if video_size < 20 << 20:
                        results.append(
                            InlineQueryResultVideo(
                                **answer_dict,
                                **caption_dict,
                                video_url=media.links[0],
                                thumbnail_url=media.thumb,
                                mime_type="video/mp4",
                            ),
                        )
                        break
                else:
                    results.append(
                        await create_in_text(
                            **answer_dict,
                            text="Video is too big, send link to bot.",
                        ),
                    )
        return results

    return [
        await create_in_text(
            **data,
            text="This twitter content can't be found or downloaded.",
        ),
    ]


async def inline_pixiv(
    update: Update,
    link: Link,
    data: dict,
    user: Chat,
    bot: Bot,
) -> InlinePixiv:
    """Sends inline pixiv media

    Args:
        update (Update): current update
        link (str): pixiv link
        data (dict): inline data
        user (Chat): sender
        bot (Bot): bot to send messages to dump channel

    Returns:
        InlineInstagram: inline query result
    """
    if (art := await get_pixiv_links(link.id)) and (count := len(art.content)):
        results = []
        caption_dict = {
            "description": f"@{art.user} : {art.desc}",
            "parse_mode": PM.HTML,
            "caption": (
                PixivStyle.get_format(user.px_style, art) if user.include_link else None
            ),
        }
        ids = [1]
        parsed_ids = await pixiv_parse(link.illust, count, MAX_PIXIV_IMAGES)
        if art.type == "ugoira":
            ugoira = art.content[0]
            if ugoira.original_size < 20 << 20:
                results.append(
                    InlineQueryResultCachedVideo(
                        **data,
                        **caption_dict,
                        video_file_id=await get_cached_media(
                            bot,
                            "video",
                            ugoira.original,
                        ),
                    ),
                )
            else:
                results.append(
                    await create_in_text(
                        **data,
                        text="Ugoira is too big, send link to bot.",
                    ),
                )
        else:
            if count > 1:
                text = None
                match parsed_ids[0]:
                    case PixivParse.SUCCESS:
                        ids = parsed_ids[1]
                    case PixivParse.OUT_OF_RANGE:
                        text = f"Can't request more than {MAX_PIXIV_IMAGES} files!"
                    case PixivParse.NOT_WITHIN_RANGE:
                        text = f"The numbers are not within range: [1-{count}]!"
                    case _:
                        ids = tuple(range(1, min(count + 1, MAX_PIXIV_IMAGES + 1)))
                if text:
                    return [
                        await create_in_text(
                            **data,
                            text=text,
                        ),
                    ]
            for index, illust in enumerate(art.content, 1):
                if index not in ids:
                    continue
                answer_dict = {
                    "id": f"{data['id']}/{index}",
                    "title": data["title"].replace(":", f"/{index}:"),
                }
                results.append(
                    InlineQueryResultCachedPhoto(
                        **answer_dict,
                        **caption_dict,
                        photo_file_id=await get_cached_media(
                            bot,
                            "photo",
                            (
                                illust.original
                                if illust.original_size < 10 << 20
                                else illust.thumb
                            ),
                        ),
                    ),
                )
        return results
    return [
        await create_in_text(
            **data,
            text="This twitter content can't be found or downloaded.",
        )
    ]


async def inline_instagram(
    update: Update,
    link: Link,
    data: dict,
    user: Chat,
    bot: Bot,
) -> InlineInstagram:
    """Sends inline instagram media

    Args:
        update (Update): current update
        link (str): instagram link
        data (dict): inline data
        user (Chat): sender
        bot (Bot): bot to send messages to dump channel

    Returns:
        InlineInstagram: inline query result
    """
    if media := await get_instagram_links(link.link):
        results = []
        for index, item in enumerate(media, 1):
            answer_dict = {
                "id": f"{data['id']}/{index}",
                "title": data["title"].replace(":", f"/{index}:"),
            }
            caption_dict = {
                "description": item.source,
                "caption": item.source if user.include_link else None,
            }
            result_size = await get_content_size(item.link)
            if item.type == "image" and result_size < 10 << 20:
                results.append(
                    InlineQueryResultCachedPhoto(
                        **answer_dict,
                        **caption_dict,
                        photo_file_id=await get_cached_media(
                            bot,
                            "photo",
                            item.link,
                        ),
                    ),
                )
            elif item.type == "video" and result_size < 20 << 20:
                results.append(
                    InlineQueryResultCachedVideo(
                        **answer_dict,
                        **caption_dict,
                        video_file_id=await get_cached_media(
                            bot,
                            "video",
                            item.link,
                        ),
                    ),
                )
            else:
                results.append(
                    await create_in_text(
                        **answer_dict,
                        text="Media is too big, send link to bot.",
                    )
                )
        return results
    return [
        await create_in_text(
            **data,
            text="This instagram content can't be found or downloaded.",
        )
    ]


async def inline_tiktok(
    update: Update,
    link: Link,
    data: dict,
    user: Chat,
) -> InlineVideo:
    """Sends inline tiktok video

    Args:
        update (Update): current update
        link (str): tiktok link
        data (dict): inline data
        user (Chat): sender

    Returns:
        InlineVideo: inline query result
    """
    if video := await get_tiktok_links(link.link):
        # check size
        for vid in video.content:
            if 0 < vid.size < 20 << 20:
                data.update(
                    {
                        "video_url": vid.link,
                        "mime_type": "video/mp4",
                        "thumbnail_url": video.thumb_1,
                        "parse_mode": PM.HTML,
                        "caption": (
                            TikTokStyle.get_format(user.tt_style, video)
                            if user.include_link
                            else None
                        ),
                    },
                )
                log.info("Inline: [#%s] Appended video.", data["id"])
                return InlineQueryResultVideo(**data)
        # if file is too big
        text = "File is too big, send link to bot."
    # if there is no video
    else:
        text = "This tiktok can't be found or downloaded."
    log.info("Inline: [#%s] Error: %s.", data["id"], text)
    return await create_in_text(
        **data,
        text=text,
    )


async def inline_youtube_short(
    update: Update,
    link: Link,
    data: dict,
    user: Chat,
) -> InlineVideo:
    """Sends inline youtube short video

    Args:
        update (Update): current update
        link (str): youtube short link
        data (dict): inline data
        user (Chat): sender

    Returns:
        InlineVideo: inline query result
    """
    if video := await get_youtube_short_links(link):
        # check size
        for vid in video.content:
            if 0 < vid.size < 20 << 20:
                data["video_url"] = vid.link
                break
        # upload video if any
        if data.get("video_url", None):
            data.update(
                {
                    "mime_type": "video/mp4",
                    "thumbnail_url": video.thumb,
                    "parse_mode": PM.HTML,
                    "caption": (
                        YouTubeShortStyle.get_format(user.yts_style, video)
                        if user.include_link
                        else None
                    ),
                },
            )
            log.info("Inline: [#%s] Appended video.", data["id"])
            return InlineQueryResultVideo(**data)
        # if file is too big
        text = "File is too big, send link to bot."
    # if there is no video
    else:
        text = "This youtube short can't be found or downloaded."
    log.info("Inline: [#%s] Error: %s.", data["id"], text)
    return await create_in_text(
        **data,
        text=text,
    )


async def inliner(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Answers to inline input

    Args:
        update (Update): telegram update object
    """
    notify(update, inline=True, inline_message=update.inline_query.query)
    query, results = update.inline_query.query, []
    if not await anext(formatter(query), None):
        log.info("Inline: No query.")
        return
    bot = context.bot
    user = await update_chat(update.effective_user)
    tasks = []
    async for index, link in aenumerate(formatter(query), 1):
        log.info(
            "Inline: [#%s] Received %s link: %r.",
            index,
            LinkType.get_type(link.type),
            link.link,
        )
        data = {
            "id": str(index),
            "title": f"#{index}: {LinkType.get_type(link.type)} link",
        }
        # send video if tiktok
        match link.type:
            case LinkType.TWITTER:
                tasks.append(
                    asyncio.create_task(
                        inline_twitter(update, link, data, user, bot),
                    ),
                )
            case LinkType.INSTAGRAM:
                tasks.append(
                    asyncio.create_task(
                        inline_instagram(update, link, data, user, bot),
                    ),
                )
            case LinkType.TIKTOK:
                tasks.append(
                    asyncio.create_task(
                        inline_tiktok(update, link, data, user),
                    ),
                )
            case LinkType.YOUTUBE_SHORT:
                tasks.append(
                    asyncio.create_task(
                        inline_youtube_short(update, link, data, user),
                    ),
                )
            case LinkType.PIXIV:
                tasks.append(
                    asyncio.create_task(
                        inline_pixiv(update, link, data, user, bot),
                    )
                )
            case _:
                tasks.append(
                    asyncio.create_task(
                        create_in_text(**data, text=link.link),
                    ),
                )
    try:
        results = []
        for result in await asyncio.gather(*tasks):
            if isinstance(result, list):
                results.extend(result)
            else:
                results.append(result)
        await update.inline_query.answer(results)
    except BadRequest as ex:
        log.error("Inline: Exception occured: %s.", ex)

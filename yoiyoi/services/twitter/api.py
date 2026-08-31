"""Twitter API"""

import asyncio
import dataclasses
import datetime
import re

from typing import Optional

# download from any network now
import gallery_dl

# parse json
import httpx
import msgspec

# structured logging
import structlog

# json-serializable dataclasses
from dataclasses_json import dataclass_json

# parse datetime
from dateutil.parser import parse

# escape markdown and get file name
from yoiyoi.bot.formatters import unescape_html

# request helpers
from yoiyoi.extra.request_helpers import get_fake_headers

# requests
from yoiyoi.extra.requests import get_content_size, make_request

# settings
from yoiyoi.extra.settings import bot_settings

# link types and other info
from yoiyoi.services.constants import LINKS

# TweetMedia & TweetContent namedtuples
from yoiyoi.services.namedtuples import TweetContent, TweetMedia

# twitter api class


# get logger
log = structlog.get_logger(__name__, service="twitter")

# twitter quality
QUALITY = ("orig", "large", "medium", "small")

# twitter dictionary
TWI = LINKS["twitter"]

# twitter URL
TWITTER_LINK = "https://twitter.com"

# tweet URL
TWEET_URL = f"{TWITTER_LINK}/i/status"


@dataclass_json
@dataclasses.dataclass
class TextLink:
    text: Optional[str]
    url: str
    tcourl: Optional[str]
    indices: tuple[int, int]


class Medium:
    pass


@dataclass_json
@dataclasses.dataclass
class Photo(Medium):
    previewUrl: str
    fullUrl: str
    kind: str = "Photo"
    altText: str = ""


@dataclass_json
@dataclasses.dataclass
class VideoVariant:
    url: str
    contentType: Optional[str]
    bitrate: Optional[int]


@dataclass_json
@dataclasses.dataclass
class Video(Medium):
    thumbnailUrl: str
    variants: list[VideoVariant]
    kind: str = "Video"
    duration: Optional[float] = None
    views: Optional[int] = None
    altText: str = ""


@dataclass_json
@dataclasses.dataclass
class Gif(Medium):
    thumbnailUrl: str
    variants: list[VideoVariant]
    kind: str = "Gif"
    altText: str = ""


@dataclass_json
@dataclasses.dataclass
class User:
    username: str
    id: int
    displayname: Optional[str] = None

    @property
    def url(self):
        return f"https://twitter.com/{self.username}"

    def __str__(self):
        return self.url


@dataclass_json
@dataclasses.dataclass
class Tweet:
    url: str
    date: datetime.datetime
    rawContent: str
    renderedContent: str
    id: int
    user: User
    replyCount: int
    retweetCount: int
    likeCount: int
    quoteCount: int
    conversationId: int
    lang: str
    links: Optional[list[TextLink]] = None
    media: Optional[list[Photo | Video | Gif]] = None
    quotedTweet: Optional["Tweet"] = None

    def __str__(self):
        return self.url

    def to_dict(self):
        data = dataclass_json.config().encoder(self)
        data["_type"] = "tweet"
        return data


# set config
gallery_dl.config.set(
    ("extractor", "twitter"),
    "browser",
    "firefox:linux",
)
gallery_dl.config.set(
    ("extractor", "twitter"),
    "csrf",
    "cookies",
)
gallery_dl.config.set(
    ("extractor", "twitter"),
    "username",
    bot_settings.tw_user,
)
gallery_dl.config.set(
    ("extractor", "twitter"),
    "password",
    bot_settings.tw_pass,
)
gallery_dl.config.set(
    ("extractor", "twitter", "cookies"),
    "auth_token",
    bot_settings.tw_token,
)
gallery_dl.config.set(
    ("extractor", "twitter", "cookies"),
    "ct0",
    bot_settings.tw_cookie,
)


async def fetch_tweet_info(tweet_id: str) -> Optional[httpx.Response]:
    api_log = log.bind(api="fixtweet")
    url = f"https://api.fxtwitter.com/i/status/{tweet_id}"
    max_retries = 2
    delay = 2

    for _ in range(max_retries):
        response = await make_request(url, "GET", headers=get_fake_headers())
        if response and not response.is_error:
            return response
        api_log.debug("No tweet info found, retrying after %s seconds...", delay)
        await asyncio.sleep(delay)


async def get_from_fixtweet_api(tweet_id: int) -> Optional[Tweet]:
    api_log = log.bind(api="fixtweet")
    if response := await fetch_tweet_info(tweet_id):
        api_log.debug("Request to API succeeded.")
        try:
            response_info = msgspec.json.decode(response.content)
        except msgspec.DecodeError:
            api_log.warning("Couldn't decode json response: %r.", response.content)
            return
        api_log.debug("Loaded JSON.", json=response_info)
        # check tweet status
        if (code := response_info.get("code")) and code != 200:
            error_message = response_info.get("message", "no message provided")
            api_log.warning(
                "Failed to get tweet: code: %s | message: %s",
                code,
                error_message,
            )
            return
        if not (tweet_info := response_info.get("tweet")):
            api_log.warning("Failed to get tweet body.")
            return
        # check user
        if not (user := tweet_info.get("author")):
            api_log.error("No user info.")
            return
        tweet_user = User(
            username=user.get("screen_name", "i"),
            id=int(user.get("id", 0)),
            displayname=user.get("name", ""),
        )
        # check media
        if not (media_info := tweet_info.get("media")):
            api_log.warning("No media.")
            return
        tweet_media = []
        for medium in media_info.get("all"):
            if medium["type"] == "photo":
                tweet_media.append(
                    Photo(
                        previewUrl=medium["url"],
                        fullUrl=medium["url"],
                    )
                )

            else:
                tweet_media.append(
                    Video(
                        thumbnailUrl=medium["thumbnail_url"],
                        variants=[
                            VideoVariant(
                                url=variant["url"],
                                contentType=variant["content_type"],
                                bitrate=int(variant.get("bitrate", 0)),
                            )
                            for variant in medium["variants"]
                        ],
                        duration=(medium.get("duration") or 0),
                    )
                )
        # check links
        tweet_links = []
        for facet in tweet_info["raw_text"]["facets"]:
            if facet["type"] in {
                "mention",
                "hashtag",
                "inline_media",
                "italic",
            }:
                continue
            elif facet["type"] in {"media", "url"}:
                tweet_links.append(
                    TextLink(
                        text=facet["display"],
                        url=facet["replacement"],
                        tcourl=facet["original"],
                        indices=facet["indices"],
                    )
                )
            else:
                api_log.error("Exotic facet: %s.", facet["type"])
        # check quote
        tweet_quote = None
        if quote_info := tweet_info.get("quote"):
            tweet_quote_user = None
            if quote_user := quote_info.get("author"):
                tweet_quote_user = User(
                    username=quote_user.get("screen_name", "i"),
                    id=int(quote_user.get("id_str", 0)),
                    displayname=quote_user.get("name", ""),
                )

            tweet_quote_id = int(quote_info.get("id", 0))
            tweet_quote = Tweet(
                url=TWI["link"].format(
                    id=tweet_quote_id,
                    author=tweet_quote_user.username if tweet_quote_user else "i",
                ),
                date=parse(quote_info["created_at"]),
                rawContent=quote_info["raw_text"]["text"],
                renderedContent=quote_info["text"],
                id=tweet_quote_id,
                user=tweet_quote_user,
                replyCount=0,
                retweetCount=0,
                likeCount=0,
                quoteCount=0,
                conversationId=tweet_quote_user,
                lang=quote_info["lang"],
            )
        # return tweet info
        return Tweet(
            url=TWI["link"].format(
                id=tweet_id,
                author=tweet_user.username if tweet_user else "i",
            ),
            date=parse(tweet_info["created_at"]),
            rawContent=tweet_info["raw_text"]["text"],
            renderedContent=tweet_info["text"],
            id=tweet_id,
            user=tweet_user,
            replyCount=0,
            retweetCount=0,
            likeCount=0,
            quoteCount=0,
            conversationId=tweet_id,
            lang=tweet_info.get("lang", "en"),
            links=tweet_links,
            quotedTweet=tweet_quote,
            media=tweet_media,
        )


async def get_from_twimg_api(tweet_id: int) -> Optional[Tweet]:
    api_log = log.bind(api="twimg")
    if response := await make_request(
        "https://cdn.syndication.twimg.com/tweet-result",
        "GET",
        data="",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
            "Gecko/20100101 Firefox/114.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://platform.twitter.com",
            "Connection": "keep-alive",
            "Referer": "https://platform.twitter.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "TE": "trailers",
        },
        params={"id": str(tweet_id), "lang": "en", "token": "ghostery"},
        with_proxy=True,
    ):
        # check response
        if response.is_error:
            return
        api_log.debug("Request to API succeeded.")
        try:
            tweet_info = msgspec.json.decode(response.content)
        except msgspec.DecodeError:
            api_log.warning("Couldn't decode json response: %r.", response.content)
            return
        api_log.debug("Loaded JSON.", json=tweet_info)
        if tomb := tweet_info.get("tombstone"):
            error = tomb["text"]["text"]
            if error.startswith("Age-restricted"):
                api_log.warning("Age-restricted: %s/%s.", TWEET_URL, tweet_id)
            else:
                api_log.warning("Dead tweet: %s/%s.", TWEET_URL, tweet_id)
            return
        if tweet_info.get("note_tweet", None):
            api_log.warning("Note tweet: %s/%s.", TWEET_URL, tweet_id)
            return
        if not (
            (user := tweet_info.get("user")) and (username := user.get("screen_name"))
        ):
            api_log.error("No user found.")
            return
        tweet_user_info = User(
            username=username,
            id=int(user.get("id_str", 0)),
            displayname=user.get("name", ""),
        )
        tweet_media_info = []
        if not (media_info := tweet_info.get("mediaDetails")):
            api_log.warning("No media tweet.")
            return
        for medium in media_info:
            if medium["type"] == "photo":
                tweet_media_info.append(
                    Photo(
                        previewUrl=medium["media_url_https"],
                        fullUrl=medium["media_url_https"],
                    )
                )
            else:
                tweet_media_info.append(
                    Video(
                        thumbnailUrl=medium["media_url_https"],
                        variants=[
                            VideoVariant(
                                url=variant["url"],
                                contentType=variant["content_type"],
                                bitrate=variant.get("bitrate"),
                            )
                            for variant in medium["video_info"]["variants"]
                        ],
                        duration=(medium["video_info"].get("duration_millis") or 0)
                        / 1000,
                    )
                )
        quote_info = None
        if quote := tweet_info.get("quoted_tweet", None):
            quote_user_info = None
            if quote_user := quote.get("user"):
                quote_user_info = User(
                    username=quote_user.get("screen_name", "i"),
                    id=int(quote_user.get("id_str", 0)),
                    displayname=quote_user.get("name", ""),
                )

            quote_info = Tweet(
                url=TWI["link"].format(
                    id=quote["id_str"],
                    author=quote_user_info.username if quote_user_info else "i",
                ),
                date=parse(quote["created_at"]),
                rawContent=quote["text"],
                renderedContent=quote["text"],
                id=quote["id_str"],
                user=quote_user_info,
                replyCount=0,
                retweetCount=0,
                likeCount=0,
                quoteCount=0,
                conversationId=quote["id_str"],
                lang=quote["lang"],
            )
        return Tweet(
            url=TWI["link"].format(
                id=tweet_info["id_str"],
                author=tweet_user_info.username if tweet_user_info else "i",
            ),
            date=parse(tweet_info["created_at"]),
            rawContent=tweet_info["text"],
            renderedContent=tweet_info["text"],
            id=tweet_info["id_str"],
            user=tweet_user_info,
            replyCount=0,
            retweetCount=0,
            likeCount=0,
            quoteCount=0,
            conversationId=tweet_info["id_str"],
            lang=tweet_info["lang"],
            links=[
                TextLink(
                    text=url["display_url"],
                    url=url["expanded_url"],
                    tcourl=url["url"],
                    indices=url["indices"],
                )
                for url in tweet_info["entities"]["media"]
            ]
            or None,
            quotedTweet=quote_info,
            media=tweet_media_info,
        )


async def get_info_from_web_services(tweet_id: int) -> Optional[dict]:
    api_log = log.bind(api="webservices")
    if (
        media_info := await make_request(
            f"https://api.redketchup.io/tweetAttachments-v2?tweetId={tweet_id}", "GET"
        )
    ) and (
        tweet_info := await make_request(
            f"https://tweetpik.com/api/tweets/{tweet_id}", "GET"
        )
    ):
        try:
            media_info = msgspec.json.decode(media_info.content)
            tweet_info = msgspec.json.decode(tweet_info.content)
        except msgspec.DecodeError as ex:
            api_log.warning("Couldn't decode json response: %r.", ex.doc)
            return
        media, user, quote = (
            media_info["includes"]["media"] if media_info.get("includes") else None,
            tweet_info["users"][0],
            tweet_info.get("quote"),
        )
        return Tweet(
            url=TWI["link"].format(id=tweet_info["id"], author=user["username"]),
            date=parse(tweet_info["created_at"]),
            rawContent=tweet_info["text"],
            renderedContent=tweet_info["text"],
            id=tweet_info["id"],
            user=User(
                username=user["username"],
                id=user["id"],
                displayname=user["name"],
            ),
            replyCount=tweet_info["reply_count"],
            retweetCount=tweet_info["retweet_count"],
            likeCount=tweet_info["like_count"],
            quoteCount=0,
            conversationId=tweet_info["id"],
            lang="",
            links=[
                TextLink(
                    text=url["display_url"],
                    url=url["expanded_url"],
                    tcourl=url["url"],
                    indices=[url["start"], url["end"]],
                )
                for url in tweet_info["urls"]
                if not (
                    quote and quote["id"] in url["expanded_url"] or url.get("media_key")
                )
            ]
            or None,
            quotedTweet=(
                Tweet(
                    url=next(
                        (
                            url["expanded_url"]
                            for url in tweet_info["urls"]
                            if quote["id"] in url["expanded_url"]
                        ),
                        None,
                    ),
                    date=parse(quote["created_at"]),
                    rawContent=quote["text"],
                    renderedContent=quote["text"],
                    id=quote["id"],
                    user=User(
                        username=None,
                        id=None,
                        displayname=None,
                    ),
                    replyCount=quote["reply_count"],
                    retweetCount=quote["retweet_count"],
                    likeCount=quote["like_count"],
                    quoteCount=0,
                    conversationId=quote["id"],
                    lang="",
                )
                if quote
                else None
            ),
            media=(
                [
                    (
                        Photo(previewUrl=medium["url"], fullUrl=medium["url"])
                        if medium["type"] == "photo"
                        else Video(
                            thumbnailUrl=medium["preview_image_url"],
                            variants=[
                                VideoVariant(
                                    url=variant["url"],
                                    contentType=variant["content_type"],
                                    bitrate=variant.get("bit_rate"),
                                )
                                for variant in medium["variants"]
                            ],
                            duration=(medium.get("duration_ms") or 0) / 1000,
                        )
                    )
                    for medium in media
                ]
                if media
                else None
            ),
        )
    api_log.warning("No response from twitter API.")


async def get_info_from_twitter_graphql(tweet_id: int) -> Optional[dict]:
    url = f"https://x.com/i/status/{tweet_id}"
    api_log = log.bind(api="graphql", tweet_id=tweet_id, url=url)

    api_log.info("Starting Twitter GraphQL extraction...")

    try:
        # Initialize DataJob without file output
        data_job = gallery_dl.job.DataJob(url, file=None)
        api_log.debug(
            "DataJob initialized using extractor: %s",
            data_job.extractor.__class__.__name__,
        )

        # Execute extraction in a separate thread to prevent blocking asyncio
        status = await asyncio.to_thread(data_job.run)

        # 1. Log internal exception caught inside DataJob.run()
        if data_job.exception:
            api_log.error(
                "DataJob caught an internal exception during run: %s: %s",
                type(data_job.exception).__name__,
                data_job.exception,
            )

        # 2. Log summary of collected message counts
        api_log.debug(
            "Extraction finished (Status: %s) | "
            "Posts: %d | Items/Meta: %d | Messages: %d",
            status,
            len(data_job.data_post),
            len(data_job.data_meta),
            len(data_job.data),
        )

        # 3. Check for successful extractions
        if data_job.data:
            api_log.info("Successfully extracted metadata.")
            return data_job.data

        # 4. If empty, log all raw internal data emitted by gallery-dl
        api_log.warning(
            "No data extracted. Raw message dump from gallery-dl: %s",
            data_job.data,
        )

    except gallery_dl.exception.StopExtraction as ex:
        api_log.error("Twitter extraction stopped prematurely: %s", ex)
    except Exception as ex:
        api_log.exception("Unexpected error in get_info_from_twitter_graphql: %s", ex)

    return None


async def get_from_twitter_api(tweet_id: int) -> Optional[Tweet]:
    """Gets tweet info from official twitter api by tweet id

    Args:
        tweet_id (int): tweet id

    Returns:
        Optional[Tweet]: tweet dictionary
    """
    api_log = log.bind(api="graphql")
    api_data = await get_info_from_twitter_graphql(tweet_id)

    if not api_data:
        api_log.error("No data received from gallery-dl extraction.")
        return None

    post_data = None
    media_items = []

    # Unpack gallery-dl message tuples:
    # [2, post_dict] -> Message.Directory (Tweet metadata)
    # [3, url, media_dict] -> Message.Url (Media metadata)
    if isinstance(api_data, list):
        for item in api_data:
            if isinstance(item, (list, tuple)):
                msg_type = item[0]
                if msg_type == 2 and len(item) >= 2 and isinstance(item[1], dict):
                    post_data = item[1]
                elif msg_type == 3 and len(item) >= 3 and isinstance(item[2], dict):
                    media_items.append((item[1], item[2]))
            elif isinstance(item, dict):
                if not post_data:
                    post_data = item
                if "type" in item or "filename" in item:
                    media_items.append((item.get("url"), item))
    elif isinstance(api_data, dict):
        post_data = api_data

    if not post_data:
        api_log.error("Failed to extract tweet metadata.")
        return None

    api_log.debug("Loaded gallery-dl tweet metadata.", json=post_data)

    # 1. Parse User
    user_info = post_data.get("user") or post_data.get("author") or {}
    username = user_info.get("name")
    if not username:
        api_log.error("No user found in tweet metadata.")
        return None

    tweet_user = User(
        username=username,
        id=int(user_info.get("id", 0)),
        displayname=user_info.get("nick") or username,
    )

    # 2. Parse Text Content
    tweet_text = post_data.get("content", "")

    # 3. Parse Media Items
    tweet_media = []
    for media_url, media_meta in media_items:
        media_type = media_meta.get("type", "photo")

        if media_type == "photo":
            tweet_media.append(
                Photo(
                    previewUrl=media_url,
                    fullUrl=media_url,
                )
            )
        else:
            # Video or GIF
            variants = []
            if "variants" in media_meta:
                variants = [
                    VideoVariant(
                        url=v.get("url"),
                        contentType=v.get("content_type", "video/mp4"),
                        bitrate=int(v.get("bitrate", 0)),
                    )
                    for v in media_meta["variants"]
                ]
            elif media_url:
                variants = [
                    VideoVariant(
                        url=media_url,
                        contentType="video/mp4",
                        bitrate=0,
                    )
                ]

            tweet_media.append(
                Video(
                    thumbnailUrl=media_meta.get("thumbnail"),
                    variants=variants,
                    duration=float(media_meta.get("duration", 0)),
                )
            )

    # 4. Parse Quoted Tweet (if present)
    quote_info = None
    if quote_data := (post_data.get("quoted_status") or post_data.get("quote")):
        q_user_info = quote_data.get("user") or quote_data.get("author") or {}
        q_user = (
            User(
                username=q_user_info.get("name", ""),
                id=int(q_user_info.get("id", 0)),
                displayname=q_user_info.get("nick", ""),
            )
            if q_user_info
            else None
        )

        quote_info = Tweet(
            url=TWI["link"].format(
                id=quote_data.get("tweet_id"),
                author=q_user.username if q_user else "i",
            ),
            date=parse(quote_data["date"]),
            rawContent=quote_data.get("content", ""),
            renderedContent=quote_data.get("content", ""),
            id=quote_data.get("tweet_id"),
            user=q_user,
            replyCount=quote_data.get("reply_count", 0),
            retweetCount=quote_data.get("retweet_count", 0),
            likeCount=quote_data.get("favorite_count", 0),
            quoteCount=quote_data.get("quote_count", 0),
            conversationId=quote_data.get("conversation_id"),
            lang=quote_data.get("lang"),
        )

    # 5. Parse Text Links (if present)
    links = None
    if urls := post_data.get("urls"):
        links = [
            TextLink(
                text=u.get("display_url", u.get("url")),
                url=u.get("expanded_url", u.get("url")),
                tcourl=u.get("url"),
                indices=u.get("indices", [0, 0]),
            )
            for u in urls
        ]

    # Return final Tweet object
    return Tweet(
        url=TWI["link"].format(
            id=tweet_id,
            author=tweet_user.username,
        ),
        date=post_data["date"],
        rawContent=tweet_text,
        renderedContent=tweet_text,
        id=tweet_id,
        user=tweet_user,
        replyCount=post_data.get("reply_count", 0),
        retweetCount=post_data.get("retweet_count", 0),
        likeCount=post_data.get("favorite_count", 0),
        quoteCount=post_data.get("quote_count", 0),
        conversationId=post_data.get("conversation_id", tweet_id),
        lang=post_data.get("lang"),
        links=links,
        quotedTweet=quote_info,
        media=tweet_media,
    )


async def process_twitter_medium(medium: Medium) -> Optional[TweetContent]:
    """Processes twitter medium

    Args:
        medium (Medium): medium to process

    Returns:
        Optional[TweetContent]: processed content
    """
    if isinstance(medium, Photo):
        if not (matched := re.search(TWI["file"], medium.fullUrl)):
            log.critical("Couldn't parse file: %s.", medium.fullUrl)
            return
        args = matched.groupdict()
        links = tuple(TWI["image"].format(**args, size=size) for size in QUALITY)
        return TweetContent(
            "photo",
            links,
            tuple([await get_content_size(link) for link in links]),
            medium.previewUrl,
            0,
        )
    elif isinstance(medium, Video) or isinstance(medium, Gif):
        links = tuple(
            animated.url
            for animated in sorted(
                medium.variants,
                key=lambda x: x.bitrate or 0,
                reverse=True,
            )
            if animated.contentType == "video/mp4"
        )
        return TweetContent(
            "gif" if len(medium.variants) == 1 else "video",
            links,
            tuple([await get_content_size(link) for link in links]),
            medium.thumbnailUrl,
            medium.duration,
        )
    else:
        log.critical("Unknown medium format: %s.", medium.__class__.__name__)
        return


async def get_twitter_media(media: list[Medium]) -> Optional[list[TweetContent]]:
    """Collects media links from tweet

    Args:
        media (list[Medium]): tweet media list

    Returns:
        Optional[list[TweetContent]]: tweet content list
    """
    content = []
    for medium in media:
        if not (item := await process_twitter_medium(medium)):
            return
        content.append(item)
    return content


async def process_tweet(tweet: Tweet) -> Optional[TweetMedia]:
    """Processes tweet for media

    Args:
        tweet (Tweet): tweet dictionary

    Returns:
        Optional[TweetMedia]: twitter media namedtuple
    """
    if not (content := await get_twitter_media(tweet.media)):
        log.error("Exception occured: No links.")
        return
    text: str = tweet.rawContent
    # replace short links with full
    if tweet.links:
        for link in tweet.links:
            text = text.replace(link.tcourl, link.url)
    # remove media link from text
    text = re.sub(TWI["media"], "", text)
    # place other links after 2 new lines
    if tweet.quotedTweet and hasattr(tweet.quotedTweet, "url"):
        text = f"{text}\n\n{tweet.quotedTweet.url}"
    return TweetMedia(
        TWI["link"].format(id=tweet.id, author=tweet.user.username),
        int(tweet.id),
        int(tweet.user.id),
        tweet.user.displayname,
        tweet.user.username,
        tweet.date,
        await unescape_html(text.strip()),
        content,
    )


async def get_twitter_links(
    tweet_id: int | str, json: bool = False
) -> Optional[TweetMedia]:
    """Gets twitter media links

    Args:
        tweet_id (int | str): tweet id

    Returns:
        Optional[TweetMedia]: twitter media namedtuple
    """
    try:
        tweet_id = int(tweet_id)
    except ValueError:
        log.error("Invalid tweet id.")
        return

    for get_tweet in (
        get_from_twimg_api,  # from twitter
        # get_from_twitter_api,  # great
        get_from_fixtweet_api,  # great
    ):
        if tweet := await get_tweet(tweet_id):
            break
    else:
        log.error("No tweet.")
        return
    if not tweet.media:
        log.error("No media.")
        return
    if json:
        return msgspec.json.decode(tweet.to_json())
    return await process_tweet(tweet)

"""Twitter module"""

import dataclasses
import datetime
import os
import re

from typing import Optional

# download from any network now
import gallery_dl

# parse json
import orjson

# structured logging
import structlog

# json-serializable dataclasses
from dataclasses_json import dataclass_json, DataClassJsonMixin

# parse datetime
from dateutil.parser import parse

# twitter api class
from gallery_dl.extractor.twitter import TwitterAPI

# link types and other info
from yoiyoi.api import LINKS

# TweetMedia & TweetContent namedtuples
from yoiyoi.api.namedtuples import TweetContent, TweetMedia

# escape markdown and get file name
from yoiyoi.bot.formatters import unescape_html

# fake headers and request helpers
from yoiyoi.extra.request_helpers import get_content_size, make_request

# settings
from yoiyoi.extra.settings import bot_settings

# get logger
log = structlog.get_logger(__name__)

# twitter quality
QUALITY = ("orig", "large", "medium", "small")

# twitter dictionary
TWI = LINKS["twitter"]

# tweet URL
TWEET_URL = "https://twitter.com/web/status"


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
    altText: str = ''


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
    altText: str = ''


@dataclass_json
@dataclasses.dataclass
class Gif(Medium):
    thumbnailUrl: str
    variants: list[VideoVariant]
    kind: str = "Gif"
    altText: str = ''


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
gallery_dl.config.set(("extractor", "twitter"), "browser", "firefox:linux")
gallery_dl.config.set(("extractor", "twitter"), "csrf", "cookies")
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


async def get_from_twimg_api(tweet_id: int) -> Optional[Tweet]:
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
        proxy=True,
    ):
        # check response
        if response.is_error:
            return
        log.debug("Request to API succeeded.")
        try:
            tweet_info = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            log.warning("Couldn't decode json response: %r.", response.content)
            return
        log.debug("JSON: %r.", tweet_info)
        if tomb := tweet_info.get("tombstone"):
            error = tomb["text"]["text"]
            if error.startswith("Age-restricted"):
                log.warning("Age-restricted: %s/%s.", TWEET_URL, tweet_id)
            else:
                log.warning("Dead tweet: %s/%s.", TWEET_URL, tweet_id)
            return
        if not (user := tweet_info.get("user")):
            log.error("Scraping failed.")
            return
        if not (media_info := tweet_info.get("mediaDetails")):
            log.warning("No media tweet.")
            return
        quote_info = None
        if quote := tweet_info.get("quoted_tweet", None):
            quote_info = Tweet(
                url=TWI["link"].format(
                    id=quote["id_str"],
                    author=quote["user"]["screen_name"],
                ),
                date=parse(quote["created_at"]),
                rawContent=quote["text"],
                renderedContent=quote["text"],
                id=quote["id_str"],
                user=User(
                    username=quote["user"]["screen_name"],
                    id=quote["user"]["id_str"],
                    displayname=quote["user"]["name"],
                ),
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
                author=user["screen_name"],
            ),
            date=parse(tweet_info["created_at"]),
            rawContent=tweet_info["text"],
            renderedContent=tweet_info["text"],
            id=tweet_info["id_str"],
            user=User(
                username=user["screen_name"],
                id=user["id_str"],
                displayname=user["name"],
            ),
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
                for url in tweet_info["entities"]["urls"]
            ]
            or None,
            quotedTweet=quote_info,
            media=(
                [
                    (
                        Photo(
                            previewUrl=medium["media_url_https"],
                            fullUrl=medium["media_url_https"],
                        )
                        if medium["type"] == "photo"
                        else Video(
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
                    for medium in media_info
                ]
                if media_info
                else None
            ),
        )


async def get_info_from_web_services(tweet_id: int) -> Optional[dict]:
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
            media_info = orjson.loads(media_info.content)
            tweet_info = orjson.loads(tweet_info.content)
        except orjson.JSONDecodeError as ex:
            log.warning("Couldn't decode json response: %r.", ex.doc)
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
    log.warning("No response from twitter API.")


async def get_info_from_twitter_graphql(tweet_id: int) -> Optional[dict]:
    try:
        data_job = gallery_dl.job.DataJob(
            f"https://twitter.com/web/status/{tweet_id}",
            file=os.devnull,
        )
        data_job.extractor.initialize()
        data_job.extractor.api = TwitterAPI(data_job.extractor)
        if data := data_job.extractor.tweets():
            return data
        log.error("Twitter GraphQL: No data.")
    except gallery_dl.exception.StopExtraction:
        log.error("Twitter GraphQL: Invalid data.")
    except Exception as ex:
        log.error("Twitter GraphQL: Excection occured: %s.", ex.args)
    return


async def get_from_twitter_api(tweet_id: int) -> Optional[Tweet]:
    """Gets tweet info from official twitter api by tweet id

    Args:
        tweet_id (int): tweet id

    Returns:
        Optional[Tweet]: tweet dictionary
    """
    if api_data := await get_info_from_twitter_graphql(tweet_id):
        for data in api_data:
            if not (tweet_info := data.get("legacy", None)):
                log.error("Scraping failed.")
                return
            if not (tweet_info["entities"].get("media", None)):
                log.error("No media.")
                return
            quote_info = None
            quote = data.get("quoted_status_result", None)
            if quote and "tombstone" not in quote["result"]:
                if "tweet" in quote["result"]:
                    if "legacy" in quote["result"]["tweet"]:
                        qinfo = quote["result"]["tweet"]["legacy"]
                        qid = quote["result"]["tweet"].get("rest_id")
                        qcore = quote["result"]["tweet"]["core"]
                else:
                    qinfo = quote["result"].get("legacy")
                    qid = quote["result"].get("rest_id")
                    qcore = None
                if not qinfo:
                    log.debug("No quote was found: %s.", quote["result"])
                    return
                if len(api_data) > 1 and qid == api_data[1]["rest_id"]:
                    quoted_user_info = api_data[1]["core"]["user_results"]["result"][
                        "legacy"
                    ]
                    quoted_user = User(
                        username=quoted_user_info["screen_name"],
                        id=int(api_data[1]["legacy"]["user_id_str"]),
                        displayname=quoted_user_info["name"],
                    )
                elif qcore:
                    quser = qcore["user_results"]["result"]
                    quoted_user = User(
                        username=quser["legacy"]["screen_name"],
                        id=int(quser["rest_id"]),
                        displayname=quser["legacy"]["name"],
                    )
                else:
                    quoted_user = None
                quote_info = Tweet(
                    url=tweet_info["quoted_status_permalink"]["expanded"],
                    date=parse(qinfo["created_at"]),
                    rawContent=qinfo["full_text"],
                    renderedContent=qinfo["full_text"],
                    id=qinfo["id_str"],
                    user=quoted_user,
                    replyCount=qinfo["reply_count"],
                    retweetCount=qinfo["retweet_count"],
                    likeCount=qinfo["favorite_count"],
                    quoteCount=qinfo["quote_count"],
                    conversationId=qinfo["conversation_id_str"],
                    lang=qinfo["lang"],
                )
            media_info = tweet_info["extended_entities"]["media"]
            user = data["core"]["user_results"]["result"]["legacy"]
            return Tweet(
                url=TWI["link"].format(
                    id=tweet_info["id_str"],
                    author=user["screen_name"],
                ),
                date=parse(tweet_info["created_at"]),
                rawContent=tweet_info["full_text"],
                renderedContent=tweet_info["full_text"],
                id=tweet_info["id_str"],
                user=User(
                    username=user["screen_name"],
                    id=tweet_info["user_id_str"],
                    displayname=user["name"],
                ),
                replyCount=tweet_info["reply_count"],
                retweetCount=tweet_info["retweet_count"],
                likeCount=tweet_info["favorite_count"],
                quoteCount=tweet_info["quote_count"],
                conversationId=tweet_info["id_str"],
                lang=tweet_info["lang"],
                links=[
                    TextLink(
                        text=url["display_url"],
                        url=url["expanded_url"],
                        tcourl=url["url"],
                        indices=url["indices"],
                    )
                    for url in tweet_info["entities"]["urls"]
                ]
                or None,
                quotedTweet=quote_info,
                media=(
                    [
                        (
                            Photo(
                                previewUrl=medium["media_url_https"],
                                fullUrl=medium["media_url_https"],
                            )
                            if medium["type"] == "photo"
                            else Video(
                                thumbnailUrl=medium["media_url_https"],
                                variants=[
                                    VideoVariant(
                                        url=variant["url"],
                                        contentType=variant["content_type"],
                                        bitrate=variant.get("bitrate"),
                                    )
                                    for variant in medium["video_info"]["variants"]
                                ],
                                duration=(
                                    medium["video_info"].get("duration_millis") or 0
                                )
                                / 1000,
                            )
                        )
                        for medium in media_info
                    ]
                    if media_info
                    else None
                ),
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
    text = re.sub(TWI["t.co"], "", text)
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
    if not (
        tweet := (
            await get_from_twimg_api(tweet_id) or await get_from_twitter_api(tweet_id)
        )
    ):
        log.error("No tweet.")
        return
    if not tweet.media:
        log.error("No media.")
        return
    if json:
        return orjson.loads(tweet.to_json())
    return await process_tweet(tweet)

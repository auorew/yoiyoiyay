"""Namedtuple module"""
from collections import namedtuple

# main namedtuple for any links
Link = namedtuple(
    "Link",
    (
        "type",
        "link",
        "id",
        "illust",
        "info",
    ),
)

InstaMedia = namedtuple(
    "InstaMedia",
    (
        "source",
        "prev",
        "link",
        "type",
        "name",
    ),
)

TikTokMedia = namedtuple(
    "TikTokMedia",
    (
        "source",
        "id",
        "kind",
        "author",
        "author_name",
        "desc",
        "thumb_0",
        "thumb_1",
        "content",
        "info_source",
        "advinfo_source",
    ),
)

TikTokVideo = namedtuple(
    "TikTokVideo",
    (
        "link",
        "size",
    ),
)

TikTokPhoto = namedtuple(
    "TikTokPhoto",
    (
        "link",
        "size",
        "prev",
        "name",
    ),
)

YouTubeShortMedia = namedtuple(
    "YouTubeShortMedia",
    (
        "source",
        "id",
        "title",
        "desc",
        "thumb",
        "channel_id",
        "channel_name",
        "duration",
        "content",
    ),
)

YouTubeShortContent = namedtuple(
    "YouTubeShortContent",
    (
        "link",
        "size",
    ),
)

TweetMedia = namedtuple(
    "TwitterMedia",
    (
        "source",
        "id",
        "user_id",
        "user",
        "username",
        "date",
        "desc",
        "content",
    ),
)

TweetContent = namedtuple(
    "TweetContent",
    (
        "type",
        "links",
        "sizes",
        "thumb",
    ),
)

PixivMedia = namedtuple(
    "PixivMedia",
    (
        "source",
        "id",
        "type",
        "user_id",
        "user",
        "username",
        "date",
        "title",
        "desc",
        "content",
    ),
)

PixivContent = namedtuple(
    "PixivContent",
    (
        "id",
        "original",
        "original_size",
        "thumb",
        "thumb_size",
    ),
)

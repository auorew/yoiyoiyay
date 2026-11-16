"""Services constants"""

import re

from enum import Enum, auto

# twitter carousel reference style parameters
TWITTER_CAROUSEL_REF_HEIGHT = 327.35
TWITTER_CAROUSEL_MARGIN = 4.0
TWITTER_CAROUSEL_GAP = 4.0
TWITTER_CAROUSEL_RADIUS = 8.0
TWITTER_CAROUSEL_FILL = None


# link types
class LinkType(Enum):
    """Represents link types"""

    DISCORD = auto()
    TWITTER = auto()
    PIXIV = auto()
    TIKTOK = auto()
    INSTAGRAM = auto()
    YOUTUBE_SHORT = auto()
    XIAOHONGSHU = auto()

    @classmethod
    def get_type(cls, value: int) -> str:
        """Gets link type name

        Args:
            value (int): link type id

        Returns:
            str: link type name
        """
        try:
            return cls(value).name.replace("_", " ").lower()
        except ValueError:
            return "unknown"

    @classmethod
    def validate(cls, value: int) -> bool:
        """Validates link type id

        Args:
            value (int): link type id

        Returns:
            bool: existence of link type id
        """
        return value in {e.value for e in cls}


# tiktok media kind
class TikTokMediaKind(Enum):
    VIDEO = auto()
    SLIDESHOW = auto()


_NEXT_URL = (
    r"https?:\/\/"
    r"|\b(?:twitter|x|pixiv|tiktok|instagram|instagr|youtube|discordapp|xhslink)"
    r"\.(?:com|net|am|cn)\/"
)
# one query/value character: not whitespace, '!', '+', '^', and not a URL start
_TOK = rf"(?:(?!{_NEXT_URL})[^\s!+\^])"
# a number token for selections: 1-3 digits (never eats part of a longer id)
_NUM = r"\d{1,3}(?!\d)(?:-\d{1,3}(?!\d))?"

# remaining URL path (after an id) that must be consumed so the tail can follow it
_PATH_REST = rf"(?:\/(?:(?!{_NEXT_URL})[^\s?!+\^])*)?"

_TAIL_QUERY = rf"[?&]{_TOK}+"
# non-selection services historically allowed one '+' inside a query value
_TAIL_QUERY_PLUS = rf"[?&]{_TOK}+(?:\+{_TOK}*)?"
# caret flag: a lone '^' or query-style '&^' / '?^' (not emoticons like ^_^)
_TAIL_CARET = r"(?:[ \t]*|[?&])\^(?![^\s+&?!])"
# selection: + 1-3 / +1,3 / +1 3 (horizontal whitespace only)
_TAIL_SELECTION = rf"[ \t]*\+[ \t]*{_NUM}(?:[ \t.,]+{_NUM})*"
# caption: !! text !!  (single line, bounded, possessive to avoid backtracking)
_TAIL_CAPTION = r"[ \t]*!![ \t]++\S.{0,1000}?[ \t]++!!"


def _link_re(head: str, *, selection: bool = False) -> str:
    """Builds a link regex: link head + strict, URL-safe tail group."""
    parts = [_TAIL_QUERY if selection else _TAIL_QUERY_PLUS, _TAIL_CARET]
    if selection:
        parts.append(_TAIL_SELECTION)
    parts.append(_TAIL_CAPTION)
    tail = "(?P<tail>(?:" + "|".join(parts) + ")*)"
    return head + tail


# link dictionary
LINKS = {
    "discord": {
        "re": _link_re(
            r"""(?x)
        (?:
            (?:discordapp\.(?:(?:com)|(?:net)))\/
            (?:(?:attachments)|(?:external))\/
            (?P<id>[\w\-]+)
        )
        """ + _PATH_REST,
            selection=False,
        ),
        "link": "",
        "type": LinkType.DISCORD,
    },
    "twitter": {
        "re": _link_re(
            r"""(?x)
            (?:
                (?:twitter|x)\.
                (?:com)\/
                (?P<author>[^/?#\s]+)\/
                (?:status(?:es)?\/)
            )
            (?P<id>\d+)
        """,
            selection=True,
        ),
        "file": r"""(?x)
            (?:
                (?:media\/)
                |
                (?:\d+x\d+\/)
                |
                (?:tweet_video\/)
            )
            (?P<id>[^\.\?]+)
            (?:
                (?:\?.*format\=)
                |
                (?:\.)
            )
            (?P<format>\w+)
        """,
        "link": "https://twitter.com/{author}/status/{id}",
        "media": r"""(?x)
            (?:\s)?
            (?:
                (?:https:\/\/t\.co\/\w{10})
            |
                (?:
                    (?:http(s)?\:)\/\/
                    (?:twitter|x)\.com\/
                    (?:[^\/]+)\/
                    (?:status(?:es)?)\/
                    (?:\d+)\/
                    (?:photo|video)
                    (?:\/\d+)?
                )
            )$
        """,
        "image": "https://pbs.twimg.com/media/{id}?format={format}&name={size}",
        "type": LinkType.TWITTER,
    },
    "pixiv": {
        "re": _link_re(
            r"""(?x)
            (?:
                (?:pixiv\.net)\/
                (?:member_illust\.php\?(?:\w+\=\w+\&)*illust_id\=)
                |
                (?:(?:\w{2}\/)?artworks\/)
            )
            (?P<id>\d+)
        """,
            selection=True,
        ),
        "file": r"""(?x)
            (?:\/(?P<id>\d+(?:_p(?P<illust>\d+))?)\.)
            (?P<format>\w+)
        """,
        "link": "https://www.pixiv.net/artworks/{id}",
        "type": LinkType.PIXIV,
    },
    "tiktok": {
        "re": _link_re(
            r"""(?x)
            (?:
                (?:(?:www|m)\.)?
                (?:tiktok\.com\/)
                (?:v|embed|trending|\@[\w\.]+\/(?:video|photo))
                (?:\/)?
                (?:\?shareId=)?
            )
            (?P<id>\d+)
        """,
            selection=False,
        ),
        "file": r"""(?x)
        (?:
            (?:.+)\/
            (?P<id>[\w\-]+)
            (?:\.(?P<ext>\w{3,4}))?
            (?:\?)
        )
        """,
        "info": r"(?:\@(?P<author>[\w\.]+)\/(?P<type>video|photo)\/(?P<id>\d+))",
        "link": "https://www.tiktok.com/@web/video/{id}",
        "source": "https://www.tiktok.com/@{author}/{type}/{id}",
        "fallback": "https://www.tiktok.com/@{author}/video/{id}",
        "type": LinkType.TIKTOK,
    },
    "vtiktok": {
        "re": _link_re(
            r"""(?x)
            (?:
                (?P<pre>\b\w{2,3}\b)\.
                (?:tiktok\.com\/)
                (?:t\/)?
            )
            (?P<id>[\w]{9})
        """,
            selection=False,
        ),
        "link": "https://www.tiktok.com/t/{id}",
        "type": LinkType.TIKTOK,
    },
    "instagram": {
        "re": _link_re(
            r"""(?x)
        (?:
            (?:instagram\.com|instagr\.(?:am|com))\/
            (?:p|reel|tv)\/
        )
        (?P<id>[\w\-]{39}|[\w\-]{11})(?![\w\-])
        """,
            selection=False,
        ),
        "file": r"""(?x)
        (?:
            (?:.+)\/
            (?P<id>[\w\-]+)
            (?:\.(?P<ext>\w{3,4}))?
            (?:\?)
        )
        """,
        "link": "https://instagram.com/p/{id}",
        "type": LinkType.INSTAGRAM,
    },
    "youtube_short": {
        "re": _link_re(
            r"""(?x)
        (?:
            (?:youtube\.com)\/
            (?:shorts\/|watch\?v=)
        )
        (?P<id>[\w\-]{11})
        """,
            selection=False,
        ),
        "thumb": "https://i.ytimg.com/vi/{0}/maxres2.jpg",
        "link": "https://www.youtube.com/shorts/{id}",
        "type": LinkType.YOUTUBE_SHORT,
    },
    "xiaohongshu": {
        "re": _link_re(
            r"""(?x)
        (?:
            (?:http(?:s)?\:\/\/)?
            (?:xhslink\.(?:com|cn)\/o\/)
            (?P<id>\w+)
        )
        """,
            selection=False,
        ),
        "link": "https://xhslink.cn/o/{id}",
        "type": LinkType.XIAOHONGSHU,
    },
}


# compile every regex once, at import time (invalid patterns fail fast here)
_REGEX_KEYS = ("re", "file", "media", "info")
for _entry in LINKS.values():
    for _key in _REGEX_KEYS:
        if _key in _entry:
            _entry[_key] = re.compile(_entry[_key])

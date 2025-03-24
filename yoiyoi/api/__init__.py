"""API module"""

from enum import Enum, auto


# link types
class LinkType(Enum):
    """Represents link types"""

    DISCORD = auto()
    TWITTER = auto()
    PIXIV = auto()
    TIKTOK = auto()
    INSTAGRAM = auto()
    YOUTUBE_SHORT = auto()

    _names = {
        DISCORD: "discord",
        TWITTER: "twitter",
        PIXIV: "pixiv",
        TIKTOK: "tiktok",
        INSTAGRAM: "instagram",
        YOUTUBE_SHORT: "youtube short",
    }

    @classmethod
    def get_type(cls, value: int) -> str:
        """Gets link type name

        Args:
            value (int): link type id

        Returns:
            str: link type name
        """
        return cls._names.get(value, "unknown")

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


# link dictionary
LINKS = {
    "discord": {
        "re": r"""(?x)
        (?:
            (?:discordapp\.(?:(?:com)|(?:net)))\/
            (?:(?:attachments)|(?:external))\/
            (?P<id>[\w\-]+)
        )
        """,
        "link": "",
        "type": LinkType.DISCORD,
    },
    "twitter": {
        "re": r"""(?x)
            (?:
                (?:twitter|x)\.
                (?:com)\/
                (?P<author>.+?)\/
                (?:status(?:es)?\/)
            )
            (?P<id>\d+)
            (?:[&?]\w+\=[\w\-]+)*
            (?:
                (?:\s*\+\s*)
                (?P<illust>(?:\d{1,3}(?:-\d{1,3})?[\s\.\,\+]*)+)
            )?
            (?:
                (?:\s*!!\s+)
                (?P<info>[^!]+)
                (?:\s!!)
            )?
        """,
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
        "t.co": r"https:\/\/t\.co\/\w{10}$",
        "image": "https://pbs.twimg.com/media/{id}?format={format}&name={size}",
        "type": LinkType.TWITTER,
    },
    "pixiv": {
        "re": r"""(?x)
            (?:
                (?:pixiv\.net)\/
                (?:member_illust\.php\?(?:\w+\=\w+\&)*illust_id\=)
                |
                (?:(?:\w{2}\/)?artworks\/)
            )
            (?P<id>\d+)
            (?:
                (?:[&?]\w+\=[\w\-]+)*
                (?:\s*\+\s*)
                (?P<illust>(?:\d{1,3}(?:-\d{1,3})?[\s\.\,\+]*)+)
            )?
            (?:
                (?:\s*!!\s+)
                (?P<info>[^!]+)
                (?:\s!!)
            )?
        """,
        "file": r"""(?x)
            (?:\/(?P<id>\d+(?:_p(?P<illust>\d+))?)\.)
            (?P<format>\w+)
        """,
        "link": "https://www.pixiv.net/artworks/{id}",
        "type": LinkType.PIXIV,
    },
    "tiktok": {
        "re": r"""(?x)
            (?:
                (?:(?:www|m)\.)?
                (?:tiktok.com\/)
                (?:v|embed|trending|\@[\w\.]+\/(?:video|photo))
                (?:\/)?
                (?:\?shareId=)?
            )
            (?P<id>\d+)
        """,
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
        "re": r"""(?x)
            (?:
                (?P<pre>\b\w{2,3}\b)\.
                (?:tiktok.com\/)
                (?:t\/)?
            )
            (?P<id>[\w]{9})
        """,
        "link": "https://www.tiktok.com/t/{id}",
        "type": LinkType.TIKTOK,
    },
    "instagram": {
        "re": r"""(?x)
        (?:
            (?:instagram\.com|instagr\.(?:am|com))\/
            (?:p|reel|tv)\/
        )
        (?P<id>[\w\-]{39}|[\w\-]{11})
        """,
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
        "re": r"""(?x)
        (?:
            (?:youtube\.com)\/
            (?:shorts\/|watch\?v=)
        )
        (?P<id>[\w\-]{11})
        """,
        "thumb": "https://i.ytimg.com/vi/{0}/maxres2.jpg",
        "link": "https://www.youtube.com/shorts/{id}",
        "type": LinkType.YOUTUBE_SHORT,
    },
}

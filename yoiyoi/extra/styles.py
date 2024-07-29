"""Styles module"""

from abc import ABC, abstractmethod
from html import escape as escape_html

# PixivMedia & TweetMedia namedtuples
from ..api.namedtuples import PixivMedia, TikTokMedia, TweetMedia, YouTubeShortMedia


class AbstractSwitcher(ABC):
    """Abstract style class"""

    @classmethod
    @abstractmethod
    def get_next(cls, value: int) -> int:
        pass

    @classmethod
    @abstractmethod
    def validate(cls, value: int) -> bool:
        pass

    @classmethod
    @abstractmethod
    def get_option(cls, value: int) -> int:
        pass


class Switcher(AbstractSwitcher):
    """Represents base switcher for any purposes."""

    name = "Base"
    field = "base_switcher"
    options = () = range(0)

    @classmethod
    def get_next(cls, value: int) -> int:
        return (value + 1) % len(cls.options)

    @classmethod
    def validate(cls, value: int) -> bool:
        return value in cls.options

    @classmethod
    def get_option(cls, value: int) -> int:
        return value % len(cls.options)


class Style(Switcher):
    """Represents base style for other styles."""

    name = "Base"
    field = "base_style"
    options = () = range(0)

    @classmethod
    def get_next(cls, value: int) -> int:
        return (value + 1) % len(cls.options)

    @classmethod
    def validate(cls, value: int) -> bool:
        return value in cls.options

    @classmethod
    def get_option(cls, value: int) -> int:
        return value % len(cls.options)

    @classmethod
    def get_example(cls, value: int) -> str:
        return NotImplemented

    @classmethod
    def get_format(cls, **kwargs) -> str:
        return NotImplemented


class TwitterStyle(Style):
    """Represents twitter style."""

    name = "Twitter"
    field = "tw_style"
    options = (
        IMAGE_LINK,
        IMAGE_LINK_DESC,
        IMAGE_INFO_EMBED_LINK,
        IMAGE_INFO_EMBED_LINK_DESC,
    ) = range(4)

    @classmethod
    def get_example(cls, value: int) -> str:
        link = "https://www\\.twitter\\.com/"
        match value:
            case cls.IMAGE_LINK:
                return "\\[ `Image(s)` \\]\n\nLink"
            case cls.IMAGE_LINK_DESC:
                return "\\[ `Image(s)` \\]\n\nLink\n\nDescription"
            case cls.IMAGE_INFO_EMBED_LINK:
                return f"\\[ `Image(s)` \\]\n\n[Author \\| @Username]({link})"
            case cls.IMAGE_INFO_EMBED_LINK_DESC:
                return (
                    f"\\[ `Image(s)` \\]\n\n[Author \\| @Username]({link})"
                    "\n\nDescription"
                )
            case _:
                return "Unknown"

    @classmethod
    def get_format(
        cls,
        style: int,
        art: TweetMedia,
    ) -> str:
        user, username, link = (
            escape_html(art.user),
            escape_html(art.username),
            escape_html(art.source),
        )
        desc = art.desc.replace("<br />", "\n")
        match style:
            case cls.IMAGE_LINK:
                return link
            case cls.IMAGE_LINK_DESC:
                return f"{link}\n\n{desc}"
            case cls.IMAGE_INFO_EMBED_LINK:
                return f"<a href='{link}'>{user} | @{username}</a>"
            case cls.IMAGE_INFO_EMBED_LINK_DESC:
                return f"<a href='{link}'>{user} | @{username}</a>\n\n{desc}"
            case _:
                return link


class PixivStyle(Style):
    """Represents pixiv style."""

    name = "Pixiv"
    field = "px_style"
    options = (
        IMAGE_LINK,
        IMAGE_LINK_DESC,
        IMAGE_INFO_LINK,
        IMAGE_INFO_EMBED_LINK,
        IMAGE_INFO_EMBED_LINK_DESC,
    ) = range(5)

    @classmethod
    def get_example(cls, value: int) -> str:
        link = "https://www\\.pixiv\\.net/"
        match value:
            case cls.IMAGE_LINK:
                return "\\[ `Image(s)` \\]\n\nLink"
            case cls.IMAGE_LINK_DESC:
                return "\\[ `Image(s)` \\]\n\nLink\n\nDescription"
            case cls.IMAGE_INFO_LINK:
                return "\\[ `Image(s)` \\]\n\nTitle \\| Author\nLink"
            case cls.IMAGE_INFO_EMBED_LINK:
                return f"\\[ `Image(s)` \\]\n\n[Title \\| Author]({link})"
            case cls.IMAGE_INFO_EMBED_LINK_DESC:
                return (
                    f"\\[ `Image(s)` \\]\n\n[Author \\| @Username]({link})"
                    "\n\n*Title*\n\nDescription"
                )
            case cls.INFO_LINK:
                return "Artwork \\| Author\nLink"
            case cls.INFO_EMBED_LINK:
                return f"[Artwork \\| Author]({link})"
            case _:
                return "Unknown"

    @classmethod
    def get_format(
        cls,
        style: int,
        art: PixivMedia,
    ) -> str:
        user, username, link, title = (
            escape_html(art.user),
            escape_html(art.username),
            escape_html(art.source),
            escape_html(art.title),
        )
        desc = art.desc.replace("<br />", "\n")
        match style:
            case cls.IMAGE_INFO_LINK:
                return f"{title} | {user}\n{link}"
            case cls.IMAGE_INFO_EMBED_LINK:
                return f"<a href='{link}'>{title} | {user}</a>"
            case cls.IMAGE_INFO_EMBED_LINK_DESC:
                return (
                    f"<a href='{link}'>{user} | @{username}</a>"
                    f"\n\n<b>{title}</b>"
                    f"\n\n{desc}"
                )
            case cls.IMAGE_LINK_DESC:
                return f"{link}\n\n{desc}"
            case cls.IMAGE_LINK | _:
                return link


class TikTokStyle(Style):
    """Represents tiktok style."""

    name = "TikTok"
    field = "tt_style"
    options = (
        VIDEO_LINK,
        VIDEO_LINK_DESC,
        VIDEO_INFO_LINK,
        VIDEO_INFO_EMBED_LINK,
        VIDEO_INFO_EMBED_LINK_DESC,
    ) = range(5)

    @classmethod
    def get_example(cls, value: int) -> str:
        link = "https://www\\.tiktok\\.com/"
        match value:
            case cls.VIDEO_LINK:
                return "\\[ `Video` \\]\n\nLink"
            case cls.VIDEO_LINK_DESC:
                return "\\[ `Video` \\]\n\nLink\n\nDescription"
            case cls.VIDEO_INFO_LINK:
                return "\\[ `Video` \\]\n\nAuthor \\| @Username\n\nLink"
            case cls.VIDEO_INFO_EMBED_LINK:
                return f"\\[ `Video` \\]\n\n[Author \\| @Username]({link})"
            case cls.VIDEO_INFO_EMBED_LINK_DESC:
                return (
                    f"\\[ `Video` \\]\n\n[Author \\| @Username]({link})" "\n\nDescription"
                )
            case _:
                return "Unknown"

    @classmethod
    def get_format(
        cls,
        style: int,
        vid: TikTokMedia,
    ) -> str:
        user, username, link, desc = (
            escape_html(vid.author_name),
            escape_html(vid.author),
            escape_html(vid.source),
            escape_html(vid.desc),
        )
        match style:
            case cls.VIDEO_LINK_DESC:
                return f"{link}\n\n{desc}"
            case cls.VIDEO_INFO_LINK:
                return f"{user} | @{username}\n\n{link}"
            case cls.VIDEO_INFO_EMBED_LINK:
                return f"<a href='{link}'>{user} | @{username}</a>"
            case cls.VIDEO_INFO_EMBED_LINK_DESC:
                return f"<a href='{link}'>{user} | @{username}</a>\n\n{desc}"
            case cls.VIDEO_LINK | _:
                return link


class YouTubeShortStyle(Style):
    """Represents pixiv style."""

    name = "YouTube Short"
    field = "yts_style"
    options = (
        VIDEO_LINK,
        VIDEO_LINK_TITLE,
        VIDEO_LINK_TITLE_DESC,
        VIDEO_INFO_LINK,
        VIDEO_INFO_EMBED_LINK,
        VIDEO_INFO_EMBED_LINK_DESC,
    ) = range(6)

    @classmethod
    def get_example(cls, value: int) -> str:
        link = "https://www\\.youtube\\.com/"
        match value:
            case cls.VIDEO_LINK:
                return "\\[ `Video` \\]\n\nLink"
            case cls.VIDEO_LINK_TITLE:
                return "\\[ `Video` \\]\n\nLink\n\nTitle"
            case cls.VIDEO_LINK_TITLE_DESC:
                return "\\[ `Video` \\]\n\nLink\n\n*Title*\n\nDescription"
            case cls.VIDEO_INFO_LINK:
                return "\\[ `Video` \\]\n\nTitle \\| Author\n\nLink"
            case cls.VIDEO_INFO_EMBED_LINK:
                return f"\\[ `Video` \\]\n\n[Title \\| Author]({link})"
            case cls.VIDEO_INFO_EMBED_LINK_DESC:
                return f"\\[ `Video` \\]\n\n[Title \\| Author]({link})" "\n\nDescription"
            case _:
                return "Unknown"

    @classmethod
    def get_format(
        cls,
        style: int,
        vid: YouTubeShortMedia,
    ) -> str:
        title, user, link, desc = (
            escape_html(vid.title),
            escape_html(vid.channel_name),
            escape_html(vid.source),
            escape_html(vid.desc),
        )
        match style:
            case cls.VIDEO_LINK_TITLE:
                return f"{link}\n\n{title}"
            case cls.VIDEO_LINK_TITLE_DESC:
                return f"{link}\n\n<b>{title}</b>\n\n{desc}"
            case cls.VIDEO_INFO_LINK:
                return f"{title} | {user}\n\n{link}"
            case cls.VIDEO_INFO_EMBED_LINK:
                return f"<a href='{link}'>{title} | {user}</a>"
            case cls.VIDEO_INFO_EMBED_LINK_DESC:
                return f"<a href='{link}'>{title} | {user}</a>\n\n{desc}"
            case cls.VIDEO_LINK | _:
                return link


class TikTokMode(Switcher):
    """Represents tiktok slideshow modes."""

    name = "TikTok slideshow mode"
    field = "tt_slide_mode"
    options = (
        VIDEO,
        SLIDE,
        # VIDEO_SLIDE,
    ) = range(2)

    @classmethod
    def get_example(cls, value: int) -> str:
        match value:
            case cls.VIDEO:
                return r"The bot will now send only a *video* for a slideshow tiktok\."
            case cls.SLIDE:
                return r"The bot will now send only *sildes* for a slideshow tiktok\."
            case _:
                return "Unknown"

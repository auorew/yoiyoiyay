"""Database schema"""

from typing import Annotated, Optional

# sqlalchemy modules
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

# media styles
from yoiyoi.extra.styles import (
    PixivStyle,
    TikTokMode,
    TikTokStyle,
    TwitterStyle,
    YouTubeShortStyle,
)

# get declarative base class
from . import Base

bool0 = Annotated[bool, mapped_column(default=False)]
bool1 = Annotated[bool, mapped_column(default=True)]


class Chat(Base):
    """Table for storing telegram chat data"""

    __tablename__ = "chat"

    # chat id
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # chat type
    type: Mapped[str]
    # chat name
    name: Mapped[Optional[str]]
    # chat username / link
    chat_link: Mapped[Optional[str]]
    # last info (currently not used, reserved for anything)
    last_info: Mapped[Optional[dict]] = mapped_column(JSONB)

    # twitter original mode
    tw_orig: Mapped[bool0]
    # twitter style
    tw_style: Mapped[int] = mapped_column(default=0)

    @validates("tw_style")
    def validate_twitter_style(self, key: str, value: int) -> int:
        """Validates twitter style

        Args:
            key (str): field name
            value (int): twitter style value

        Raises:
            ValueError: twitter style value is invalid

        Returns:
            int: new twitter style value
        """
        if TwitterStyle.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    # pixiv original mode
    px_orig: Mapped[bool0]
    # pixiv style
    px_style: Mapped[int] = mapped_column(default=0)

    @validates("px_style")
    def validate_pixiv_style(self, key: str, value: int) -> int:
        """Validates pixiv style

        Args:
            key (str): field name
            value (int): pixiv style value

        Raises:
            ValueError: pixiv style value is invalid

        Returns:
            int: new pixiv style value
        """
        if PixivStyle.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    # tiktok hd mode
    tt_orig: Mapped[bool0]
    # tiktok style
    tt_style: Mapped[int] = mapped_column(default=0)
    # tiktok slideshow mode
    tt_slide_mode: Mapped[int] = mapped_column(default=0)

    @validates("tt_style")
    def validate_tiktok_style(self, key: str, value: int) -> int:
        """Validates tiktok style

        Args:
            key (str): field name
            value (int): tiktok style value

        Raises:
            ValueError: tiktok style value is invalid

        Returns:
            int: new tiktok style value
        """
        if TikTokStyle.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    @validates("tt_slide_mode")
    def validate_tiktok_slide_mode(self, key: str, value: int) -> int:
        """Validates tiktok slideshow mode

        Args:
            key (str): field name
            value (int): tiktok mode value

        Raises:
            ValueError: tiktok mode value is invalid

        Returns:
            int: new tiktok mode value
        """
        if TikTokMode.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    # instagram original mode
    in_orig: Mapped[bool0]
    # instagram style
    in_style: Mapped[int] = mapped_column(default=0)

    # youtube short mode
    yts_orig: Mapped[bool0]
    # youtube short style
    yts_style: Mapped[int] = mapped_column(default=0)

    @validates("yts_style")
    def validate_youtube_short_style(self, key: str, value: int) -> int:
        """Validates youtube short style

        Args:
            key (str): field name
            value (int): youtube short style value

        Raises:
            ValueError: youtube short style value is invalid

        Returns:
            int: new youtube short style value
        """
        if YouTubeShortStyle.validate(value):
            return value
        raise ValueError(f"Invalid value {value!r} for field {key!r}.")

    # include link of media
    include_link: Mapped[bool0]

    # special options for channels

    # ignore forwarded messages
    ignore_fw: Mapped[bool0]
    # delete original message after posting
    delete_link: Mapped[bool0]

    # banned
    is_banned: Mapped[bool0]
    # banned reason
    banned_for: Mapped[Optional[str]]

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "chat_link": self.chat_link,
            "include_link": self.include_link,
            "delete_link": self.delete_link,
            "ignore_fw": self.ignore_fw,
            "last_info": self.last_info,
            # ban
            "is_banned": self.is_banned,
            "banned_for": self.banned_for,
            # twitter
            "tw_orig": self.tw_orig,
            "tw_style": self.tw_style,
            # pixiv
            "px_orig": self.px_orig,
            "px_style": self.px_style,
            # instagra,
            "in_orig": self.in_orig,
            "in_style": self.in_style,
            # tiktok
            "tt_orig": self.tt_orig,
            "tt_style": self.tt_style,
            "tt_slide_mode": self.tt_slide_mode,
            # youtube short
            "yts_orig": self.yts_orig,
            "yts_style": self.yts_style,
        }

from unittest.mock import AsyncMock, MagicMock

import pytest

from yoiyoi.db.models import Chat
from yoiyoi.services.constants import LinkType
from yoiyoi.services.namedtuples import Link


@pytest.fixture
def mock_chat():
    """Creates a dummy database Chat model."""
    chat = MagicMock(spec=Chat)
    chat.id = 123456789
    chat.type = "private"
    chat.tt_orig = False
    chat.delete_link = False
    return chat


@pytest.fixture
def mock_update():
    """Creates a dummy Telegram Update object."""
    update = MagicMock()
    update.update_id = 99999
    update.effective_chat.id = 123456789
    update.effective_message.reply_video = AsyncMock()
    update.effective_message.reply_photo = AsyncMock()
    update.effective_message.delete = AsyncMock()
    return update


@pytest.fixture
def sample_tiktok_link():
    """Creates a sample Link namedtuple."""
    return Link(
        type=LinkType.TIKTOK,
        link="https://www.tiktok.com/@messagetodaniel/video/7663145201396878609",
        id=7663145201396878609,
    )

import pytest

from yoiyoi.services.tiktok.api import get_tiktok_links
from yoiyoi.services.tiktok.sender import TikTokSender


@pytest.mark.asyncio
async def test_tiktok_api_fetch(sample_tiktok_link):
    """Tests direct API response parsing."""
    media = await get_tiktok_links(sample_tiktok_link.link)
    assert media is not None
    assert len(media.content) > 0


@pytest.mark.asyncio
async def test_tiktok_sender_run(mock_update, sample_tiktok_link, mock_chat):
    """Tests full execution flow of TikTokSender."""
    sender = TikTokSender(mock_update, sample_tiktok_link, mock_chat)
    # Execute sender pipeline (downloads, formats, and batches media)
    await sender.run()

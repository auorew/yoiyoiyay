from pathlib import Path

from PIL import Image

from yoiyoi.bot import MAX_THUMB_FILE_SIZE, MAX_THUMB_SIZE
from yoiyoi.bot.formatters import make_thumb_name
from yoiyoi.bot.processors import _process_thumbnail_sync


def test_make_thumb_name():
    import asyncio

    name1 = asyncio.run(make_thumb_name("test_video.mp4"))
    assert name1 == "test_video.thumb.jpeg"

    name2 = asyncio.run(make_thumb_name("my.complex.video.name.mov"))
    assert name2 == "my.complex.video.name.thumb.jpeg"


def test_process_thumbnail_large_image(tmp_path: Path):
    # 1920x1080 RGBA PNG
    input_file = tmp_path / "large.png"
    img = Image.new("RGBA", (1920, 1080), (255, 100, 50, 200))
    img.save(input_file, format="PNG")

    result = _process_thumbnail_sync(input_file)
    assert result is not None
    assert result.exists()
    assert result.suffix == ".jpeg"
    assert result.stat().st_size < MAX_THUMB_FILE_SIZE

    with Image.open(result) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"
        assert out_img.width <= MAX_THUMB_SIZE
        assert out_img.height <= MAX_THUMB_SIZE
        assert out_img.width == 320
        assert out_img.height == 180


def test_process_thumbnail_small_image(tmp_path: Path):
    # 150x200 RGB WebP
    input_file = tmp_path / "small.webp"
    img = Image.new("RGB", (150, 200), (0, 128, 255))
    img.save(input_file, format="WEBP")

    result = _process_thumbnail_sync(input_file)
    assert result is not None
    assert result.exists()
    assert result.suffix == ".jpeg"
    assert result.stat().st_size < MAX_THUMB_FILE_SIZE

    with Image.open(result) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"
        assert out_img.width <= MAX_THUMB_SIZE
        assert out_img.height <= MAX_THUMB_SIZE
        assert out_img.width == 150
        assert out_img.height == 200


def test_process_thumbnail_with_cropping(tmp_path: Path):
    # 1280x720 horizontal image for a 9:16 vertical video (e.g. YouTube Short)
    input_file = tmp_path / "short_thumb.jpg"
    img = Image.new("RGB", (1280, 720), (100, 200, 100))
    img.save(input_file, format="JPEG")

    result = _process_thumbnail_sync(
        input_file, video_width=1080, video_height=1920, crop=True
    )
    assert result is not None
    assert result.exists()
    assert result.suffix == ".jpeg"
    assert result.stat().st_size < MAX_THUMB_FILE_SIZE

    with Image.open(result) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.width <= MAX_THUMB_SIZE
        assert out_img.height <= MAX_THUMB_SIZE
        # Aspect ratio should match vertical 9:16 (1080/1920 = 0.5625)
        aspect = out_img.width / out_img.height
        assert abs(aspect - (1080 / 1920)) < 0.05


def test_process_thumbnail_palette_with_transparency(tmp_path: Path):
    input_file = tmp_path / "palette.png"
    img = Image.new("P", (400, 400))
    img.info["transparency"] = 0
    img.save(input_file, format="PNG")

    result = _process_thumbnail_sync(input_file)
    assert result is not None
    assert result.exists()
    assert result.suffix == ".jpeg"
    assert result.stat().st_size < MAX_THUMB_FILE_SIZE

    with Image.open(result) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"
        assert out_img.width <= MAX_THUMB_SIZE
        assert out_img.height <= MAX_THUMB_SIZE


class DummyService:
    from yoiyoi.services.base import BaseSender

    # inherit prepare_thumbnail and _process_and_flush
    prepare_thumbnail = BaseSender.prepare_thumbnail
    _process_and_flush = BaseSender._process_and_flush

    def __init__(self, storage_dir):
        self.storage_dir = storage_dir
        self.storage = set()
        self.update_id = 1234
        from unittest.mock import MagicMock

        self.log = MagicMock()
        self.update = MagicMock()
        self.chat = MagicMock()
        self.chat.delete_link = False
        self.sent_any = False


def test_base_service_prepare_thumbnail_from_url(tmp_path: Path):
    import asyncio

    from unittest.mock import AsyncMock

    svc = DummyService(tmp_path)
    # create a raw downloaded thumb file
    raw_thumb = tmp_path / "raw.png"
    img = Image.new("RGBA", (800, 600), (10, 20, 30, 255))
    img.save(raw_thumb, format="PNG")

    svc.download_helper = AsyncMock(return_value=(raw_thumb, raw_thumb))
    video_file = tmp_path / "video.mp4"
    video_file.touch()

    final_thumb = asyncio.run(
        svc.prepare_thumbnail(
            thumb="https://example.com/thumb.png",
            videopath=video_file,
            video_width=800,
            video_height=600,
        )
    )
    assert final_thumb is not None
    assert final_thumb.exists()
    assert final_thumb.name == "video.thumb.jpeg"
    assert final_thumb in svc.storage

    with Image.open(final_thumb) as thumb_img:
        assert thumb_img.format == "JPEG"
        assert thumb_img.mode == "RGB"
        assert thumb_img.width <= MAX_THUMB_SIZE
        assert thumb_img.height <= MAX_THUMB_SIZE


def test_base_service_prepare_thumbnail_fallback_to_video(tmp_path: Path):
    import asyncio

    from unittest.mock import AsyncMock, patch

    svc = DummyService(tmp_path)
    video_file = tmp_path / "video2.mp4"
    video_file.touch()

    # create a mock extracted thumb
    extracted_thumb = tmp_path / "video2.raw_thumb.jpeg"
    img = Image.new("RGB", (1280, 720), (50, 50, 50))
    img.save(extracted_thumb, format="JPEG")

    with patch(
        "yoiyoi.services.base.create_thumbnail",
        new=AsyncMock(return_value=extracted_thumb),
    ):
        final_thumb = asyncio.run(
            svc.prepare_thumbnail(
                thumb=None,
                videopath=video_file,
                video_width=1280,
                video_height=720,
            )
        )

    assert final_thumb is not None
    assert final_thumb.exists()
    assert final_thumb.name == "video2.thumb.jpeg"
    assert final_thumb in svc.storage

    with Image.open(final_thumb) as thumb_img:
        assert thumb_img.format == "JPEG"
        assert thumb_img.width <= MAX_THUMB_SIZE
        assert thumb_img.height <= MAX_THUMB_SIZE


def test_base_service_input_file_uses_thumb_name(tmp_path: Path):
    import asyncio

    from unittest.mock import patch

    from yoiyoi.services.base import MediaItem

    svc = DummyService(tmp_path)
    video_file = tmp_path / "twitter_123.mp4"
    video_file.write_bytes(b"dummy video data")

    thumb_file = tmp_path / "twitter_123.thumb.jpeg"
    img = Image.new("RGB", (320, 180), (10, 20, 30))
    img.save(thumb_file, format="JPEG")

    item = MediaItem(
        path=video_file,
        type="video",
        caption="test",
        thumb_path=thumb_file,
        width=320,
        height=180,
        duration=10,
    )

    captured_media_group = []

    async def fake_reply_media_group(message, media, **kwargs):
        nonlocal captured_media_group
        captured_media_group = media
        return [MagicMock()]

    from unittest.mock import MagicMock

    with patch("yoiyoi.services.base.reply_media_group", new=fake_reply_media_group):
        asyncio.run(svc._process_and_flush([item]))

    assert len(captured_media_group) == 1
    input_media_video = captured_media_group[0]
    assert input_media_video.thumbnail is not None
    # Verify thumbnail filename is the thumbnail filename, NOT the video filename
    assert input_media_video.thumbnail.filename == "twitter_123.thumb.jpeg"
    assert input_media_video.media.filename == "twitter_123.mp4"

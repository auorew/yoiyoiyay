from pathlib import Path

import pytest

from PIL import Image

from yoiyoi.bot.formatters import formatter, parse_link_modifiers
from yoiyoi.bot.processors import _stitch_images_sync
from yoiyoi.services.constants import LinkType


@pytest.mark.anyio
async def test_parse_link_modifiers_twitter():
    tail = "?a=3AfDKgfEbqRjHBnwKXo&s=19&stitch=black+2-5!! my caption !!"
    illust, info, action = parse_link_modifiers(tail, service="twitter")
    assert illust == "2-5"
    assert info == "my caption"
    assert action == {
        "stitch": {"fill": "black", "gap": None, "radius": None, "margin": None}
    }


@pytest.mark.anyio
async def test_parse_link_modifiers_transparent_stitch():
    tail = "&stitch + 1-4"
    illust, info, action = parse_link_modifiers(tail, service="twitter")
    assert illust == "1-4"
    assert info is None
    assert action == {
        "stitch": {"fill": None, "gap": None, "radius": None, "margin": None}
    }


@pytest.mark.anyio
async def test_parse_link_modifiers_stitch_hex_color():
    tail = "&stitch=#15202b"
    illust, info, action = parse_link_modifiers(tail, service="twitter")
    assert illust is None
    assert info is None
    assert action == {
        "stitch": {"fill": "#15202b", "gap": None, "radius": None, "margin": None}
    }


@pytest.mark.anyio
async def test_parse_link_modifiers_compound_stitch():
    tail = "&stitch=fill:black;gap:8;radius:12;margin:10,20 + 1-3 !! compound test !!"
    illust, info, action = parse_link_modifiers(tail, service="twitter")
    assert illust == "1-3"
    assert info == "compound test"
    assert action == {
        "stitch": {
            "fill": "black",
            "gap": 8.0,
            "radius": 12.0,
            "margin": [10.0, 20.0],
        }
    }


@pytest.mark.anyio
async def test_parse_link_modifiers_explicit_transparent_fill():
    tail1 = "&stitch=fill:none"
    _, _, action1 = parse_link_modifiers(tail1, service="twitter")
    assert action1["stitch"]["fill"] is None

    tail2 = "&stitch=fill:transparent"
    _, _, action2 = parse_link_modifiers(tail2, service="twitter")
    assert action2["stitch"]["fill"] is None


@pytest.mark.anyio
async def test_parse_link_modifiers_only_first_selection():
    tail = "+4-7+1,2,3"
    illust, info, action = parse_link_modifiers(tail, service="twitter")
    assert illust == "4-7"
    assert action == {}


@pytest.mark.anyio
async def test_parse_link_modifiers_only_first_action():
    tail = "&stitch=white&stitch=black"
    illust, info, action = parse_link_modifiers(tail, service="twitter")
    assert action["stitch"]["fill"] == "white"


@pytest.mark.anyio
async def test_parse_link_modifiers_pixiv_ignores_twitter_actions():
    tail = "?p=1&stitch=black+1-3!! pixiv art !!"
    illust, info, action = parse_link_modifiers(tail, service="pixiv")
    assert illust == "1-3"
    assert info == "pixiv art"
    assert action == {}


@pytest.mark.anyio
async def test_formatter_twitter_full_url():
    url = (
        "https://twitter.com/onlymikufans/status/2121569300767273039"
        "?a=3AfDKgfEbqRjHBnwKXo&s=19&stitch=black+2-5!! caption !!"
    )
    links = [_link async for _link in formatter(url)]
    assert len(links) == 1
    link = links[0]
    assert link.type == LinkType.TWITTER
    assert link.id == "2121569300767273039"
    assert link.illust == "2-5"
    assert link.info == "caption"
    assert link.action["stitch"]["fill"] == "black"


@pytest.mark.anyio
async def test_formatter_twitter_tracking_only():
    url = (
        "https://twitter.com/onlymikufans/status/2121569300767273039"
        "?s=20&t=abcdef12345"
    )
    links = [_link async for _link in formatter(url)]
    assert len(links) == 1
    link = links[0]
    assert link.type == LinkType.TWITTER
    assert link.id == "2121569300767273039"
    assert link.illust is None
    assert link.info is None
    assert link.action == {}


@pytest.mark.anyio
async def test_formatter_pixiv_artwork():
    url = "https://www.pixiv.net/en/artworks/152060517" " + 1,2-4 !! cool gallery !!"
    links = [_link async for _link in formatter(url)]
    assert len(links) == 1
    link = links[0]
    assert link.type == LinkType.PIXIV
    assert link.id == "152060517"
    assert link.illust == "1,2-4"
    assert link.info == "cool gallery"
    assert link.action == {}


@pytest.mark.anyio
async def test_formatter_multiple_urls_in_one_message():
    message_text = (
        "Check this out:\n"
        "https://twitter.com/onlymikufans/status/2121569300767273039"
        "?s=20&stitch=white + 1-4 !! cute comic !!\n"
        "and also this pixiv artwork:\n"
        "https://www.pixiv.net/artworks/22222222"
        "?p=2 + 3-5 !! original !!"
    )
    links = [_link async for _link in formatter(message_text)]
    assert len(links) == 2

    tw_link = links[0]
    assert tw_link.type == LinkType.TWITTER
    assert tw_link.id == "2121569300767273039"
    assert tw_link.illust == "1-4"
    assert tw_link.info == "cute comic"
    assert tw_link.action["stitch"]["fill"] == "white"

    px_link = links[1]
    assert px_link.type == LinkType.PIXIV
    assert px_link.id == "22222222"
    assert px_link.illust == "3-5"
    assert px_link.info == "original"
    assert px_link.action == {}


@pytest.mark.anyio
async def test_parse_link_modifiers_order_independence():
    # Tail with action before selection, tracking in the middle, caption at the end
    tail = "&stitch=black&ref=web+10-12!! title !!"
    illust, info, action = parse_link_modifiers(tail, service="twitter")
    assert illust == "10-12"
    assert info == "title"
    assert action["stitch"]["fill"] == "black"


@pytest.mark.anyio
async def test_parse_link_modifiers_empty_or_plain_tail():
    assert parse_link_modifiers("", service="twitter") == (None, None, {})
    assert parse_link_modifiers("?s=20&t=foo", service="twitter") == (None, None, {})
    assert parse_link_modifiers("?s=20&stitch", service="pixiv") == (None, None, {})


def test_stitch_images_differing_sizes_and_orientations(tmp_path: Path):
    # Test combining portrait and landscape images with smallest height
    # Landscape: 800x400 (smallest height = 400)
    p1 = tmp_path / "land.png"
    Image.new("RGBA", (800, 400), (255, 0, 0, 255)).save(p1)
    # Portrait: 300x600
    p2 = tmp_path / "port.png"
    Image.new("RGBA", (300, 600), (0, 255, 0, 255)).save(p2)
    # Square: 500x500
    p3 = tmp_path / "sq.png"
    Image.new("RGBA", (500, 500), (0, 0, 255, 255)).save(p3)

    out = tmp_path / "mixed_stitched.png"
    _stitch_images_sync([p1, p2, p3], out, fill_color="#000000")

    res = Image.open(out)
    target_h = 400
    scale = target_h / 327.35
    margin = round(4 * scale)
    gap = round(4 * scale)

    # p1: 800
    # p2: 300 * (400 / 600) = 200
    # p3: 500 * (400 / 500) = 400
    expected_w = 2 * margin + 800 + 200 + 400 + 2 * gap
    expected_h = 2 * margin + 400

    assert res.size == (expected_w, expected_h)
    assert res.mode == "RGBA"
    # Background should be black
    assert res.getpixel((0, 0)) == (0, 0, 0, 255)


def test_stitch_images_dimensions_and_scaling(tmp_path: Path):
    # Image 1: 500x1000
    p1 = tmp_path / "img1.png"
    # Image 2: 600x500 (smallest height = 500)
    p2 = tmp_path / "img2.png"
    # Image 3: 400x800
    p3 = tmp_path / "img3.png"

    Image.new("RGBA", (500, 1000), (255, 0, 0, 255)).save(p1)
    Image.new("RGBA", (600, 500), (0, 255, 0, 255)).save(p2)
    Image.new("RGBA", (400, 800), (0, 0, 255, 255)).save(p3)

    out = tmp_path / "stitched.png"
    _stitch_images_sync([p1, p2, p3], out)

    res = Image.open(out)
    target_h = 500
    scale = target_h / 327.35
    margin = round(4 * scale)
    gap = round(4 * scale)

    # Scaled widths:
    # img1: 500 * (500/1000) = 250
    # img2: 600
    # img3: 400 * (500/800) = 250
    expected_w = 2 * margin + 250 + 600 + 250 + 2 * gap
    expected_h = 2 * margin + 500

    assert res.size == (expected_w, expected_h)
    assert res.mode == "RGBA"
    # Corner pixel in margin should be transparent by default
    assert res.getpixel((0, 0))[3] == 0


def test_stitch_images_color_fill(tmp_path: Path):
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    Image.new("RGBA", (300, 300), (255, 0, 0, 255)).save(p1)
    Image.new("RGBA", (300, 300), (0, 255, 0, 255)).save(p2)

    out = tmp_path / "stitched_colored.png"
    _stitch_images_sync([p1, p2], out, fill_color="white")

    res = Image.open(out)
    assert res.mode == "RGBA"
    # Corner pixel should be white (255, 255, 255, 255)
    assert res.getpixel((0, 0)) == (255, 255, 255, 255)


def test_stitch_images_custom_parameters(tmp_path: Path):
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    Image.new("RGBA", (400, 400), (255, 0, 0, 255)).save(p1)
    Image.new("RGBA", (400, 400), (0, 255, 0, 255)).save(p2)

    out = tmp_path / "custom_stitched.png"
    # Custom gap, border radius, and asymmetric margins [top/bottom, left/right]
    _stitch_images_sync(
        [p1, p2],
        out,
        fill_color="blue",
        gap=10,
        border_radius=16,
        frame_margins=[10, 20],
    )

    res = Image.open(out)
    target_h = 400
    scale = target_h / 327.35
    left_px = round(20 * scale)
    top_px = round(10 * scale)
    resolved_gap = round(10 * scale)

    expected_w = (2 * left_px) + 400 + 400 + resolved_gap
    expected_h = (2 * top_px) + 400

    assert res.size == (expected_w, expected_h)
    assert res.mode == "RGBA"
    # Check background fill color (blue)
    assert res.getpixel((0, 0)) == (0, 0, 255, 255)


@pytest.mark.anyio
async def test_formatter_multiple_urls_with_variations():
    """Test multiple URLs with varying stitch parameters and extra text"""
    message_text = (
        "First is a comic:\n"
        "https://twitter.com/onlymikufans/status/2121569300767273039"
        "?a=3AfDKgfEbqRjHBnwKXo&s=19&stitch=white + 1-4 !! white comic !!\n\n"
        "Then a portrait:\n"
        "https://www.pixiv.net/en/artworks/152060517"
        " + 1,2-4 !! cool portrait !!\n\n"
        "Finally this one:\n"
        "https://twitter.com/onlymikufans/status/2121569300767273040"
        "?stitch=black + 3-5 !! black background !!\n\n"
        "Extra text at the end."
    )
    links = [_link async for _link in formatter(message_text)]
    assert len(links) == 3

    # Twitter link 1 (found first due to LINKS dictionary iteration order)
    tw_link1 = links[0]
    assert tw_link1.type == LinkType.TWITTER
    assert tw_link1.id == "2121569300767273039"
    assert tw_link1.illust == "1-4"
    assert tw_link1.info == "white comic"
    assert tw_link1.action["stitch"]["fill"] == "white"

    # Twitter link 2
    tw_link2 = links[1]
    assert tw_link2.type == LinkType.TWITTER
    assert tw_link2.id == "2121569300767273040"
    assert tw_link2.illust == "3-5"
    assert tw_link2.info == "black background"
    assert tw_link2.action["stitch"]["fill"] == "black"

    # Pixiv link (found after Twitter links due to formatter iteration order)
    px1 = links[2]
    assert px1.type == LinkType.PIXIV
    assert px1.id == "152060517"
    assert px1.illust == "1,2-4"
    assert px1.info == "cool portrait"
    assert px1.action == {}


@pytest.mark.anyio
async def test_formatter_pixiv_full_url_with_all_modifiers():
    url = (
        "https://www.pixiv.net/en/artworks/98765432"
        "?mode=manga&p=3&order=desc&stitch=white&ref=search + 1-4,6-8!! "
        "detailed manga !!"
    )
    links = [_link async for _link in formatter(url)]
    assert len(links) == 1
    link = links[0]
    assert link.type == LinkType.PIXIV
    assert link.id == "98765432"
    assert link.illust == "1-4,6-8"
    assert link.info == "detailed manga"
    assert link.action == {}

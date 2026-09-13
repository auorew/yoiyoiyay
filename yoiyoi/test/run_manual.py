import asyncio

import structlog

from yoiyoi.services.tiktok.api import get_tiktok_links

# Initialize logger output for local debugging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)

TEST_URLS = [
    "https://www.tiktok.com/@osudailybanger/video/7167401459322080518",
    "https://www.tiktok.com/@codehase/photo/7266491035704888581",
    "https://vt.tiktok.com/ZSqHLs6YU/",
]


async def main():
    for url in TEST_URLS:
        print(f"Testing TikTok API with URL: {url}")
        media = await get_tiktok_links(url)

        if not media:
            print("Failed to retrieve media info.")
            return

        print(f"Kind: {media.kind}")
        print(f"Author: {media.author_name} (@{media.author})")
        print(f"Description: {media.desc}")
        print(f"Thumb: {media.thumb}")
        print(f"Content items count: {len(media.content)}")
        for item in media.content:
            print(f" - {type(item).__name__}: {item.link} (Size: {item.size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())

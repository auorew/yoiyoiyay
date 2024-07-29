"""Tracemalloc helpers module"""

import linecache
import logging
import tracemalloc

# setup logger
log = logging.getLogger(__name__)


def display_top(
    snapshot: tracemalloc.Snapshot,
    key_type: str = "lineno",
    limit: int = 10,
) -> None:
    """Display top 10 (default) lines allocating the most memory

    Args:
        snapshot (tracemalloc.Snapshot): snapshot of memory blocks
        key_type (str, optional): filename, line number or traceback. Defaults
        to "lineno".
        limit (int, optional): number of lines to show. Defaults to 10.
    """
    snapshot = snapshot.filter_traces(
        (
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, "<unknown>"),
        ),
    )
    top_stats = snapshot.statistics(key_type)

    result = [f"[ Top {limit} lines ]"]
    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        result.append(
            f"#{index}: {frame.filename}:{frame.lineno}: {stat.size / 1024:.1f} KiB"
        )
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            result.append(f"    {line}")

    other = top_stats[limit:]
    if other:
        size = sum(stat.size for stat in other)
        result.append(f"\n{len(other)} other: {size / 1024:.1f} KiB\n")
    total = sum(stat.size for stat in top_stats)
    result.append(f"Total allocated size: {total / 1024:.1f} KiB\n")

    log.info("\n".join(result))

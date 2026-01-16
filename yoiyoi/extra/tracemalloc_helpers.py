"""Tracemalloc helpers module"""

import gc
import linecache
import re
import time
import tracemalloc

from typing import Optional

# structured logging
import structlog

# setup logger
log = structlog.get_logger(__name__)


def memory_monitor_task(interval=300):
    baseline = tracemalloc.take_snapshot()
    while True:
        try:
            time.sleep(interval)
            re.purge()
            linecache.clearcache()
            gc.collect()
            current_snapshot = tracemalloc.take_snapshot()
            display_top(current_snapshot, prev_snapshot=baseline)
        except Exception as e:
            log.error(f"Memory monitor thread error: {e}")


def display_top(
    snapshot: tracemalloc.Snapshot,
    key_type: str = "lineno",
    limit: int = 10,
    prev_snapshot: Optional[tracemalloc.Snapshot] = None,
) -> None:
    """Display top 10 (default) lines allocating the most memory

    Args:
        snapshot (tracemalloc.Snapshot): snapshot of memory blocks
        key_type (str): filename, line number or traceback. Defaults to "lineno"
        limit (int): number of lines to show
        prev_snapshot (Optional[tracemalloc.Snapshot]): previous snapshot
    """
    snapshot = snapshot.filter_traces(
        (
            tracemalloc.Filter(False, tracemalloc.__file__),
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
            tracemalloc.Filter(False, "*debugpy*"),  # Ignore VS Code Debugger
            tracemalloc.Filter(False, "*pydevd*"),  # Ignore Python Debugger
            tracemalloc.Filter(False, "<unknown>"),
        )
    )
    if prev_snapshot:
        stats = snapshot.compare_to(prev_snapshot, key_type)
        title = f"[ Top {limit} Memory Changes ]"
    else:
        stats = snapshot.statistics(key_type)
        title = f"[ Top {limit} Absolute Allocations ]"
    result = [title]
    for index, stat in enumerate(stats[:limit], 1):
        frame = stat.traceback[0]
        size_kb = stat.size / 1024
        usage_str = f"{size_kb:.1f} KiB"
        if prev_snapshot:
            diff_kb = stat.size_diff / 1024
            usage_str += f" ({'+' if diff_kb > 0 else ''}{diff_kb:.1f} KiB)"
        result.append(f"#{index}: {frame.filename}:{frame.lineno}: {usage_str}")
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            result.append(f"    {line}")
    total = sum(s.size for s in stats)
    result.append(f"\nTotal tracked memory: {total / 1024:.1f} KiB")
    log.info("\n".join(result))

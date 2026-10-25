"""Current process RSS on the Linux deployment; not a Python heap estimate."""
import os
from pathlib import Path


def process_rss_bytes():
    try:
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError, AttributeError):
        return None

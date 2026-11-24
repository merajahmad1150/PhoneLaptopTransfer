"""core/timefmt.py - one place for the time stamps shown next to every transferred item."""
import time


def fmt_dt(ts: float) -> str:
    """2026-10-14 19:10:32 (local time) - shown in the desktop window."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

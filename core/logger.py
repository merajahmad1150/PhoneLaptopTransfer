"""
core/logger.py
Logging with ONE FILE PER SESSION (every time the tool is opened a new file is
created, and it is closed with a summary when the tool is closed):

    logs/sessions/session_2026-10-11_21-05-33.log

Design goals (all requested by the user):
  * Nothing hidden: DEBUG level everywhere, full tracebacks, thread names,
    unhandled errors from ANY thread and from Tk callbacks, hard crashes
    (faulthandler) and the previous session's unclean exit are all recorded.
  * No spam: identical consecutive messages are collapsed into
    "... (repeated 37 more times)" so a phone page that polls every few
    seconds can't flood the file.
  * Every session ends with a footer: duration, counts per level, transfer
    statistics, and whether it ended cleanly.
  * Secrets (the access PIN) are never written.

A GUI widget can attach via attach_gui_sink(); the web dashboard reads the
in-memory ring buffer via ring_since().
"""

import faulthandler
import logging
import os
import platform
import shutil
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

from version import APP_NAME, VERSION

_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)-7s] [%(threadName)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LOGGER_NAME = "transfer"

_gui_sinks = []
_ring = deque(maxlen=2000)       # (seq, text) for the web dashboard
_ring_seq = 0
_ring_lock = threading.Lock()

_session = {
    "path": None, "start": None, "marker": None, "ended": False,
    "fault_file": None, "handlers": [],
}
STATS = {}   # simple counters, e.g. STATS["files_received"] += 1
_stats_lock = threading.Lock()


def stat_add(key: str, amount=1) -> None:
    with _stats_lock:
        STATS[key] = STATS.get(key, 0) + amount


# ---------------------------------------------------------------------- #
# Handlers / filters
# ---------------------------------------------------------------------- #
class _CountHandler(logging.Handler):
    """Counts records per level for the session footer."""
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.counts = {}

    def emit(self, record):
        self.counts[record.levelname] = self.counts.get(record.levelname, 0) + 1


class _RingHandler(logging.Handler):
    def emit(self, record):
        global _ring_seq
        try:
            text = self.format(record)
        except Exception:
            text = record.getMessage()
        with _ring_lock:
            _ring_seq += 1
            _ring.append((_ring_seq, text))


class _GuiHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        for sink in list(_gui_sinks):
            try:
                sink(msg)
            except Exception:
                pass  # a broken GUI sink must never take down logging


class _DedupFilter(logging.Filter):
    """Collapses runs of identical messages. The first one is written; the
    repeats are counted and a single "repeated N more times" line is written
    when a different message arrives (or the session ends)."""
    def __init__(self, logger_ref):
        super().__init__()
        self._last = None
        self._count = 0
        self._last_text = ""
        self._last_seen = 0.0
        self._lock = threading.Lock()
        self._logger_ref = logger_ref

    def filter(self, record):
        if record.levelno >= logging.ERROR:
            self._flush_locked_safe()
            return True  # never collapse errors
        key = (record.levelno, record.getMessage())
        with self._lock:
            if key == self._last:
                self._count += 1
                self._last_seen = time.time()
                return False
            pending, text, seen = self._count, self._last_text, self._last_seen
            self._last = key
            self._last_text = record.getMessage()
            self._last_seen = time.time()
            self._count = 0
        if pending > 0:
            self._emit_repeat(pending, text, seen)
        return True

    def _emit_repeat(self, n, text="", seen=0.0):
        # Written through the logger, flagged so it bypasses this filter. It says WHICH line
        # repeated and when the last repeat happened (the old marker was ambiguous).
        when = time.strftime("%H:%M:%S", time.localtime(seen)) if seen else "?"
        short = (text[:110] + "...") if len(text) > 110 else text
        self._logger_ref.log(logging.DEBUG, "   ^ the line above repeated %d more time(s), last at %s: %s",
                             n, when, short, extra={"_dedup_bypass": True})

    def _flush_locked_safe(self):
        with self._lock:
            pending, text, seen = self._count, self._last_text, self._last_seen
            self._count, self._last = 0, None
        if pending > 0:
            self._emit_repeat(pending, text, seen)

    def flush_pending(self):
        self._flush_locked_safe()


class _BypassableDedup(_DedupFilter):
    def filter(self, record):
        if getattr(record, "_dedup_bypass", False):
            return True
        return super().filter(record)


class _SafeStreamHandler(logging.StreamHandler):
    """Console handler that can never raise on odd characters (Urdu/Hindi
    file names on a cp1252 console) - it replaces what it cannot print."""
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            if stream is None:
                return
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                enc = getattr(stream, "encoding", None) or "ascii"
                stream.write(msg.encode(enc, "replace").decode(enc, "replace") + self.terminator)
            self.flush()
        except Exception:
            pass


# ---------------------------------------------------------------------- #
# Public API
# ---------------------------------------------------------------------- #
def attach_gui_sink(callback) -> None:
    _gui_sinks.append(callback)


def detach_gui_sink(callback) -> None:
    if callback in _gui_sinks:
        _gui_sinks.remove(callback)


def ring_since(seq: int = 0, limit: int = 400):
    """Returns (new_seq, [lines]) for lines newer than `seq`."""
    with _ring_lock:
        items = [(s, t) for s, t in _ring if s > seq]
        last = _ring_seq
    return last, [t for _, t in items[-limit:]]


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def current_log_path():
    return _session["path"]


def _free_space_text(path: Path) -> str:
    try:
        u = shutil.disk_usage(str(path))
        return f"{u.free / 1024 ** 3:.1f} GB free of {u.total / 1024 ** 3:.1f} GB"
    except OSError:
        return "unknown"


def setup_logging(log_root: Path, keep_sessions: int = 500, level=logging.DEBUG) -> logging.Logger:
    """Start a NEW session log file. Safe to call once per process."""
    logger = logging.getLogger(_LOGGER_NAME)
    if _session["path"] is not None:
        return logger

    logger.setLevel(level)
    logger.propagate = False
    log_root = Path(log_root)
    sessions = log_root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    # Tidy up the old single-file logs from v1.x (kept, just moved aside).
    archive = log_root / "archive_old"
    for old in list(log_root.glob("transfer.log*")):
        try:
            archive.mkdir(exist_ok=True)
            old.replace(archive / old.name)
        except OSError:
            pass

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = sessions / f"session_{stamp}.log"
    n = 1
    while path.exists():  # two launches in the same second
        n += 1
        path = sessions / f"session_{stamp}_{n}.log"

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = _SafeStreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    gui_handler = _GuiHandler()
    gui_handler.setFormatter(formatter)
    ring_handler = _RingHandler()
    ring_handler.setFormatter(formatter)
    counter = _CountHandler()

    dedup = _BypassableDedup(logger)
    # The dedup filter sits on the LOGGER (applied once per record), not on each
    # handler - otherwise every handler would see the same record again and
    # wrongly count it as a repeat.
    logger.addFilter(dedup)
    for h in (file_handler, console_handler, gui_handler, ring_handler):
        h.setLevel(logging.DEBUG)
        logger.addHandler(h)
    logger.addHandler(counter)

    # Route waitress' own logger into the same sinks.
    wl = logging.getLogger("waitress")
    wl.setLevel(logging.INFO)
    wl.propagate = False
    for h in (file_handler, console_handler, gui_handler, ring_handler):
        wl.addHandler(h)

    _session.update(path=path, start=time.time(), ended=False,
                    handlers=[file_handler, console_handler, gui_handler, ring_handler, counter],
                    dedup=dedup, counter=counter)

    # Did the previous session end badly?
    marker = log_root / "active_session.txt"
    _session["marker"] = marker
    previous = None
    try:
        if marker.exists():
            previous = marker.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        marker.write_text(str(path), encoding="utf-8")
        (log_root / "latest_session.txt").write_text(str(path), encoding="utf-8")
    except OSError:
        pass

    # Hard-crash tracebacks (e.g. a crash inside Tk or a DLL) go in the same file.
    try:
        _session["fault_file"] = open(path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_session["fault_file"], all_threads=True)
    except Exception:
        pass

    _install_excepthooks(logger)

    logger.info("=" * 78)
    logger.info("SESSION START  %s v%s", APP_NAME, VERSION)
    logger.info("Log file     : %s", path)
    logger.info("Python       : %s (%s)", sys.version.replace("\n", " "), sys.executable)
    logger.info("Platform     : %s | machine=%s | pid=%s", platform.platform(), platform.machine(), os.getpid())
    logger.info("Working dir  : %s", os.getcwd())
    logger.info("Command line : %s", " ".join(sys.argv))
    logger.info("Encoding     : stdout=%s fs=%s PYTHONUTF8=%s", getattr(sys.stdout, "encoding", None),
                sys.getfilesystemencoding(), os.environ.get("PYTHONUTF8"))
    logger.info("Temp folder  : %s", os.environ.get("TEMP") or os.environ.get("TMP") or "(default)")
    logger.info("Disk space   : project drive -> %s", _free_space_text(log_root))
    logger.info("=" * 78)
    if previous:
        logger.warning("The PREVIOUS session did not end cleanly (crash, window force-closed, or power loss): %s", previous)

    _prune_old_sessions(sessions, keep_sessions, logger)
    return logger


def _prune_old_sessions(sessions: Path, keep: int, logger) -> None:
    try:
        files = sorted(sessions.glob("session_*.log"))
        extra = len(files) - max(keep, 20)
        for f in files[:max(extra, 0)]:
            f.unlink()
        if extra > 0:
            logger.info("Removed %d oldest session log(s) (keeping the newest %d)", extra, keep)
    except OSError as exc:
        logger.warning("Could not prune old session logs: %s", exc)


def _install_excepthooks(logger) -> None:
    def _fmt(exc_type, exc_value, exc_tb):
        return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    def _main_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("KeyboardInterrupt (Ctrl+C) received")
            return
        logger.critical("UNHANDLED EXCEPTION in main thread:\n%s", _fmt(exc_type, exc_value, exc_tb))

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        logger.critical("UNHANDLED EXCEPTION in thread '%s':\n%s", name,
                        _fmt(args.exc_type, args.exc_value, args.exc_traceback))

    def _unraisable(unraisable):
        logger.error("UNRAISABLE exception (%s): %r", unraisable.err_msg, unraisable.exc_value)

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable


def end_session(reason: str = "normal exit") -> None:
    """Write the footer, close the session file and clear the 'active' marker.
    Safe to call more than once."""
    if _session["ended"] or _session["path"] is None:
        return
    _session["ended"] = True
    logger = get_logger()
    try:
        _session["dedup"].flush_pending()
    except Exception:
        pass
    dur = time.time() - (_session["start"] or time.time())
    h, rem = divmod(int(dur), 3600)
    m, s = divmod(rem, 60)
    counts = getattr(_session.get("counter"), "counts", {})
    logger.info("=" * 78)
    logger.info("SESSION END   reason: %s", reason)
    logger.info("Duration     : %dh %02dm %02ds", h, m, s)
    logger.info("Log records  : %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none")
    with _stats_lock:
        stats = dict(STATS)
    if stats:
        logger.info("Statistics   : %s", ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    errs = counts.get("ERROR", 0) + counts.get("CRITICAL", 0)
    logger.info("Result       : %s", "CLEAN (no errors)" if errs == 0 else f"{errs} error(s) were recorded - please share this file")
    logger.info("=" * 78)
    for h_ in list(_session["handlers"]):
        try:
            h_.flush()
        except Exception:
            pass
    try:
        faulthandler.disable()
        if _session["fault_file"]:
            _session["fault_file"].close()
    except Exception:
        pass
    try:
        if _session["marker"] and _session["marker"].exists():
            _session["marker"].unlink()
    except OSError:
        pass
    for h_ in list(_session["handlers"]):
        try:
            logger.removeHandler(h_)
            logging.getLogger("waitress").removeHandler(h_)
            h_.close()
        except Exception:
            pass

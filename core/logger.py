"""
core/logger.py
Central logging setup. Logs everything at DEBUG level (not just INFO) to both
a rotating file and the console, with full timestamps, so crashes and edge
cases are always fully explained rather than silently swallowed.

A GUI widget (e.g. a Tkinter ScrolledText) can be attached via attach_gui_sink()
so every log line also appears live in the app window.
"""

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_gui_sinks = []  # list of callables(str) -> None, e.g. a Tkinter text widget appender


class _GuiHandler(logging.Handler):
    """Forwards formatted log records to any registered GUI sink callbacks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        for sink in list(_gui_sinks):
            try:
                sink(msg)
            except Exception:
                # Never let a broken GUI sink take down logging itself
                pass


def attach_gui_sink(callback) -> None:
    """Register a callback(str) that receives every formatted log line."""
    _gui_sinks.append(callback)


def detach_gui_sink(callback) -> None:
    if callback in _gui_sinks:
        _gui_sinks.remove(callback)


def setup_logging(log_dir: Path, level=logging.DEBUG) -> logging.Logger:
    """Configure the root 'transfer' logger. Safe to call more than once."""
    logger = logging.getLogger("transfer")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "transfer.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    gui_handler = _GuiHandler()
    gui_handler.setLevel(logging.DEBUG)
    gui_handler.setFormatter(formatter)
    logger.addHandler(gui_handler)

    # Catch anything unhandled anywhere in the process and log it in full,
    # instead of the app silently vanishing.
    def _log_unhandled(exc_type, exc_value, exc_tb):
        logger.critical(
            "UNHANDLED EXCEPTION: %s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = _log_unhandled

    logger.debug("Logging initialized. Log file: %s", log_dir / "transfer.log")
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("transfer")

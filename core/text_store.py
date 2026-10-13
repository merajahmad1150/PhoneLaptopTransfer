"""
core/text_store.py
Text shared between phone and laptop, in both directions. A thin layer over
HistoryStore so every text is saved permanently on the laptop, while the phone
page only gets the recent ones (frontend_visible_hours).

No length limit on an entry - accuracy/completeness matters more than memory.
"""

import threading

from history_store import HistoryStore, KIND_TEXT_TO_LAPTOP, KIND_TEXT_TO_PHONE
from logger import get_logger

log = get_logger()


class TextStore:
    def __init__(self, history: HistoryStore):
        self.history = history
        self._listeners = []
        self._lock = threading.Lock()

    def add_to_laptop(self, text: str, via: str = "unknown", copied: bool = False) -> dict:
        entry = self.history.add(KIND_TEXT_TO_LAPTOP, text=text, via=via, copied=copied)
        for callback in list(self._listeners):
            try:
                callback(entry)
            except Exception:
                log.error("A text listener raised an error", exc_info=True)
        return entry

    def add_to_phone(self, text: str) -> dict:
        return self.history.add(KIND_TEXT_TO_PHONE, text=text)

    def list_to_laptop(self, include_cleared: bool = False) -> list:
        return self.history.list([KIND_TEXT_TO_LAPTOP], include_cleared=include_cleared)

    def list_to_phone(self, since_id: int = 0, visible_hours: float = 0) -> list:
        return self.history.list([KIND_TEXT_TO_PHONE], since_id=since_id, visible_hours=visible_hours)

    def on_new_to_laptop(self, callback) -> None:
        """Register a callback(entry) fired whenever the phone sends text."""
        self._listeners.append(callback)

    def clear(self) -> int:
        """Hide history from the GUI lists; the saved data stays on disk."""
        return self.history.clear_visible()

"""
core/text_store.py
Text shared between phone and laptop, in both directions. A thin layer over
HistoryStore so every text is saved permanently on the laptop, while the phone
page only gets the recent ones (frontend_visible_hours).

No length limit on an entry - accuracy/completeness matters more than memory.
"""

import threading

from history_store import (HistoryStore, KIND_TEXT_TO_LAPTOP, KIND_TEXT_TO_PHONE, SCOPE_GUI, SCOPE_PHONE_TEXTS)
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
        return self.history.list([KIND_TEXT_TO_LAPTOP], include_cleared=include_cleared, scope=SCOPE_GUI)

    def list_sent_to_phone(self) -> list:
        """What the laptop sent to the phone, for the desktop window (respects the window's Clear)."""
        return self.history.list([KIND_TEXT_TO_PHONE], include_cleared=False, scope=SCOPE_GUI)

    def list_to_phone(self, since_id: int = 0, visible_hours: float = 0) -> list:
        """What the PHONE PAGE shows: newer than the visibility window and not cleared (on the phone or in the app)."""
        return self.history.list([KIND_TEXT_TO_PHONE], since_id=since_id, visible_hours=visible_hours,
                                 include_cleared=False, scope=SCOPE_PHONE_TEXTS)

    def phone_cleared_upto(self) -> int:
        return self.history.cleared_upto(SCOPE_PHONE_TEXTS)

    def on_new_to_laptop(self, callback) -> None:
        """Register a callback(entry) fired whenever the phone sends text."""
        self._listeners.append(callback)

    def clear(self) -> int:
        """Clear the lists in the desktop window AND on the phone page. Saved data stays on disk."""
        n = self.history.clear_scope(SCOPE_GUI)
        self.history.clear_scope(SCOPE_PHONE_TEXTS)
        return n

    def clear_phone_page(self) -> int:
        """The phone's own 'Clear' button: hides the list on the phone page only."""
        return self.history.clear_scope(SCOPE_PHONE_TEXTS)

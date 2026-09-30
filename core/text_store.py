"""
core/text_store.py
Thread-safe in-memory store for text shared between phone and laptop, in
both directions. No length limit is enforced on an individual entry -
accuracy/completeness matters more than saving memory here - but the
number of *entries* kept per direction is capped so a long session
doesn't grow without bound.

Runs in the same process as the Flask server and the Tkinter GUI (just
different threads), so both sides share this single instance directly -
no extra network hop needed for the GUI to "receive" what the phone sent,
or for the phone to "receive" what the GUI sent.
"""

import itertools
import threading
import time

MAX_ENTRIES_PER_DIRECTION = 200


class TextStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._to_laptop = []  # phone -> laptop
        self._to_phone = []   # laptop -> phone
        self._listeners = []  # callables(entry) notified on new phone -> laptop text

    def add_to_laptop(self, text: str) -> dict:
        entry = {"id": next(self._counter), "text": text, "ts": time.time()}
        with self._lock:
            self._to_laptop.append(entry)
            del self._to_laptop[:-MAX_ENTRIES_PER_DIRECTION]
        for callback in list(self._listeners):
            try:
                callback(entry)
            except Exception:
                pass  # a broken listener must never break text delivery
        return entry

    def add_to_phone(self, text: str) -> dict:
        entry = {"id": next(self._counter), "text": text, "ts": time.time()}
        with self._lock:
            self._to_phone.append(entry)
            del self._to_phone[:-MAX_ENTRIES_PER_DIRECTION]
        return entry

    def list_to_laptop(self) -> list:
        with self._lock:
            return list(self._to_laptop)

    def list_to_phone(self, since_id: int = 0) -> list:
        with self._lock:
            return [e for e in self._to_phone if e["id"] > since_id]

    def on_new_to_laptop(self, callback) -> None:
        """Register a callback(entry) fired whenever the phone sends text."""
        self._listeners.append(callback)

    def clear(self) -> None:
        """Wipe all text history, both directions - used by the GUI's
        Clear Text History button."""
        with self._lock:
            self._to_laptop.clear()
            self._to_phone.clear()

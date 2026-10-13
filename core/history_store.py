"""
core/history_store.py
The permanent record of everything shared through the tool.

  * Every shared item (file received from the phone, file offered to the phone,
    text either way) is appended to  data/history.jsonl  - one JSON object per
    line, so a crash can never corrupt the older lines.
  * The phone page only SHOWS items newer than `frontend_visible_hours`
    (default 6). Older items vanish from the page but stay here, on the laptop
    (and the files themselves stay in ReceivedFromPhone / ShareToPhone).
  * Texts are additionally appended to human-readable daily files in
    ReceivedText\\texts_YYYY-MM-DD.txt (open them in Notepad++ etc.).

Thread-safe: used by the web server threads and the GUI thread at once.
"""

import itertools
import json
import threading
import time
from pathlib import Path

from logger import get_logger

log = get_logger()

KIND_TEXT_TO_LAPTOP = "text_to_laptop"
KIND_TEXT_TO_PHONE = "text_to_phone"
KIND_FILE_FROM_PHONE = "file_from_phone"
KIND_FILE_TO_PHONE = "file_to_phone"


class HistoryStore:
    def __init__(self, data_dir: Path, text_dir: Path):
        self.path = Path(data_dir) / "history.jsonl"
        self.text_dir = Path(text_dir)
        self._lock = threading.RLock()
        self._entries = []
        self._cleared_upto = 0   # entries with id <= this are hidden in the GUI lists
        self._max_id = 0
        self._load()
        self._counter = itertools.count(self._max_id + 1)

    # ------------------------------------------------------------------ #
    def _load(self):
        bad = 0
        if not self.path.exists():
            log.info("History file not found yet - starting a new one: %s", self.path)
            return
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        bad += 1
                        continue
                    if obj.get("kind") == "clear":
                        self._cleared_upto = max(self._cleared_upto, int(obj.get("upto_id", 0)))
                        continue
                    self._entries.append(obj)
                    self._max_id = max(self._max_id, int(obj.get("id", 0)))
        except OSError as exc:
            log.error("Could not read history file %s: %s", self.path, exc, exc_info=True)
        log.info("History loaded: %d saved item(s)%s", len(self._entries),
                 f" ({bad} unreadable line(s) skipped)" if bad else "")

    def _append_line(self, obj: dict):
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.error("Could not write to history file %s: %s", self.path, exc, exc_info=True)

    def _write_text_file(self, entry: dict):
        try:
            self.text_dir.mkdir(parents=True, exist_ok=True)
            day = time.strftime("%Y-%m-%d", time.localtime(entry["ts"]))
            hhmmss = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
            direction = "FROM PHONE" if entry["kind"] == KIND_TEXT_TO_LAPTOP else "TO PHONE"
            with open(self.text_dir / f"texts_{day}.txt", "a", encoding="utf-8", newline="") as f:
                f.write(f"[{hhmmss}] {direction} (#{entry['id']}, {len(entry['text'])} chars)\r\n"
                        f"{entry['text']}\r\n{'-' * 60}\r\n")
        except OSError as exc:
            log.error("Could not save text to %s: %s", self.text_dir, exc, exc_info=True)

    # ------------------------------------------------------------------ #
    def add(self, kind: str, **fields) -> dict:
        with self._lock:
            entry = {"id": next(self._counter), "kind": kind, "ts": time.time()}
            entry.update(fields)
            self._entries.append(entry)
            self._append_line(entry)
        if kind in (KIND_TEXT_TO_LAPTOP, KIND_TEXT_TO_PHONE):
            self._write_text_file(entry)
        return entry

    def list(self, kinds=None, since_id: int = 0, visible_hours: float = 0, include_cleared: bool = True) -> list:
        """Entries oldest->newest. visible_hours>0 hides older ones (phone page)."""
        cutoff = time.time() - visible_hours * 3600 if visible_hours and visible_hours > 0 else 0
        with self._lock:
            out = []
            for e in self._entries:
                if kinds and e["kind"] not in kinds:
                    continue
                if e["id"] <= since_id:
                    continue
                if cutoff and e["ts"] < cutoff:
                    continue
                if not include_cleared and e["id"] <= self._cleared_upto:
                    continue
                out.append(e)
            return out

    def latest_file_entry(self, kind: str, name: str):
        with self._lock:
            for e in reversed(self._entries):
                if e["kind"] == kind and e.get("name") == name:
                    return e
        return None

    def clear_visible(self) -> int:
        """Hide everything currently in the GUI lists (data stays on disk)."""
        with self._lock:
            n = len([e for e in self._entries if e["id"] > self._cleared_upto])
            self._cleared_upto = self._max_id_locked()
            self._append_line({"kind": "clear", "upto_id": self._cleared_upto, "ts": time.time()})
        return n

    def _max_id_locked(self) -> int:
        return max((e["id"] for e in self._entries), default=self._cleared_upto)

    def counts(self) -> dict:
        with self._lock:
            c = {}
            for e in self._entries:
                c[e["kind"]] = c.get(e["kind"], 0) + 1
            return c

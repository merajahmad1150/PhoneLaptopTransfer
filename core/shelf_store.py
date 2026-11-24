"""
core/shelf_store.py
The Clip Shelf's list: texts (captions, hashtags, comment replies...) and files (documents, images, videos, mp3,
PDFs...). Saved in data/shelf.json (written atomically). Only small records are kept in memory - files are
remembered by path (or kept as a private copy in ShelfFiles\\ if you choose) - so RAM stays tiny.

File names created by the tool itself are ASCII only (id + safe name) to avoid Urdu/Hindi file-name encoding
problems; the original name is kept as the item's label.
"""

import json
import os
import re
import threading
import time
from pathlib import Path

from logger import get_logger

log = get_logger()

_KINDS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".3gp"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"},
    "pdf": {".pdf"},
    "doc": {".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx"},
    "archive": {".zip", ".rar", ".7z", ".gz"},
}
TYPE_COLORS = {"text": "#f1efff", "image": "#34d67a", "video": "#ffb020", "audio": "#ff5fa2", "pdf": "#ff6b6b",
               "doc": "#5aa9ff", "archive": "#c792ff", "folder": "#22d3b8", "file": "#a39fd0", "missing": "#6f6a9a"}


def file_type(path: str) -> str:
    if os.path.isdir(path):
        return "folder"
    ext = Path(path).suffix.lower()
    for kind, exts in _KINDS.items():
        if ext in exts:
            return kind
    return "file"


def ascii_name(name: str, limit: int = 60) -> str:
    """ASCII-only file name (non-English characters become '_')."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "file"
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:8]
    return (clean[:limit] + ("." + ext if ext else ""))


class ShelfStore:
    def __init__(self, data_path: Path, files_dir: Path):
        self.path = Path(data_path)
        self.files_dir = Path(files_dir)
        self.items = []
        self._lock = threading.RLock()
        self._timer = None
        self._load()

    # ---------------- persistence ----------------
    def _load(self):
        if not self.path.exists():
            log.info("Shelf: starting a new list (%s)", self.path)
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [i for i in data.get("items", []) if isinstance(i, dict) and "id" in i]
            log.info("Shelf: %d saved item(s) loaded", len(self.items))
        except (OSError, ValueError) as exc:
            backup = self.path.with_suffix(".json.bad")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            log.error("Shelf list was unreadable (%s) - kept as %s and started a new list", exc, backup.name)

    def save(self, now: bool = False):
        """Debounced atomic save (0.4 s after the last change)."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
            if now:
                self._write()
                return
            self._timer = threading.Timer(0.4, self._write)
            self._timer.daemon = True
            self._timer.start()

    def _write(self):
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps({"version": 1, "items": self.items}, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                log.error("Could not save the shelf list", exc_info=True)

    # ---------------- helpers ----------------
    def _next_id(self) -> int:
        return max((i["id"] for i in self.items), default=0) + 1

    def get(self, item_id: int):
        with self._lock:
            return next((i for i in self.items if i["id"] == item_id), None)

    def _insert(self, item: dict, at_top: bool = True) -> dict:
        with self._lock:
            item["id"] = self._next_id()
            item["added"] = time.time()
            self.items.insert(0, item) if at_top else self.items.append(item)
        self.save()
        return item

    # ---------------- add ----------------
    def add_text(self, text: str):
        text = text.rstrip()
        if not text.strip():
            return None
        item = self._insert({"kind": "text", "text": text})
        log.info("Shelf: text added (%d characters)", len(text))
        return item

    def add_file(self, path: str, copy: bool = False):
        src = Path(path)
        if not src.exists():
            log.warning("Shelf: cannot add '%s' - it does not exist", path)
            return None
        owned, target = False, str(src)
        if copy and src.is_file():
            self.files_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            dest = self.files_dir / f"f{int(time.time())}_{ascii_name(src.name)}"
            shutil.copy2(src, dest)
            owned, target = True, str(dest)
        item = self._insert({"kind": "file", "path": target, "label": src.name, "owned": owned})
        log.info("Shelf: file added '%s'%s", src.name, " (private copy kept)" if owned else "")
        return item

    def add_image(self, pil_image, label: str = ""):
        """Save a clipboard picture (e.g. a Win+Shift+S screenshot) as PNG inside ShelfFiles."""
        self.files_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest = self.files_dir / f"screenshot_{stamp}.png"
        n = 1
        while dest.exists():
            n += 1
            dest = self.files_dir / f"screenshot_{stamp}_{n}.png"
        pil_image.save(dest, "PNG")
        item = self._insert({"kind": "file", "path": str(dest), "label": label or dest.name, "owned": True})
        log.info("Shelf: picture added (%sx%s)", pil_image.width, pil_image.height)
        return item

    # ---------------- edit / delete ----------------
    def update_text(self, item_id: int, text: str) -> bool:
        with self._lock:
            it = self.get(item_id)
            if not it or it.get("kind") != "text":
                return False
            it["text"] = text
        self.save()
        return True

    def rename(self, item_id: int, label: str) -> bool:
        with self._lock:
            it = self.get(item_id)
            if not it:
                return False
            it["label"] = label.strip() or Path(it.get("path", "")).name
        self.save()
        return True

    def replace_file(self, item_id: int, new_path: str) -> bool:
        with self._lock:
            it = self.get(item_id)
            if not it or it.get("kind") != "file":
                return False
            self._remove_owned(it)
            it.update(path=str(new_path), owned=False, label=Path(new_path).name)
        self.save()
        return True

    def _remove_owned(self, it: dict):
        if it.get("owned"):
            try:
                Path(it["path"]).unlink()
            except OSError:
                pass

    def delete(self, item_id: int) -> bool:
        with self._lock:
            it = self.get(item_id)
            if not it:
                return False
            self._remove_owned(it)
            self.items.remove(it)
        self.save()
        log.info("Shelf: item deleted (%s)", it.get("label") or (it.get("text", "")[:30]))
        return True

    # ---------------- order ----------------
    def move(self, item_id: int, where: str) -> bool:
        """where: top | middle | bottom | up | down"""
        with self._lock:
            it = self.get(item_id)
            if not it:
                return False
            i = self.items.index(it)
            self.items.pop(i)
            n = len(self.items)
            j = {"top": 0, "bottom": n, "middle": n // 2, "up": max(i - 1, 0), "down": min(i + 1, n)}[where]
            self.items.insert(j, it)
        self.save()
        return True

    def move_to_index(self, item_id: int, index: int) -> bool:
        with self._lock:
            it = self.get(item_id)
            if not it:
                return False
            self.items.remove(it)
            self.items.insert(max(0, min(index, len(self.items))), it)
        self.save()
        return True

    # ---------------- view ----------------
    def view(self, query: str = "") -> list:
        q = query.strip().lower()
        with self._lock:
            if not q:
                return list(self.items)
            return [i for i in self.items if q in (i.get("text", "") + " " + i.get("label", "") + " " + i.get("path", "")).lower()]

    @staticmethod
    def display(item: dict) -> str:
        if item.get("kind") == "text":
            for line in item.get("text", "").splitlines():
                if line.strip():
                    return line.strip()[:90]
            return "(empty)"
        return item.get("label") or Path(item.get("path", "")).name

    @staticmethod
    def color(item: dict) -> str:
        if item.get("kind") == "text":
            return TYPE_COLORS["text"]
        p = item.get("path", "")
        if not os.path.exists(p):
            return TYPE_COLORS["missing"]
        return TYPE_COLORS.get(file_type(p), TYPE_COLORS["file"])

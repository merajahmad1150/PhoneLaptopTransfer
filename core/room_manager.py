"""
core/room_manager.py
"Shared Rooms" let someone who isn't the app's owner open the public link,
get a private room (its own folder + its own shared text feed), and pair
their own laptop browser + phone browser to it via a QR code - without
ever touching the owner's personal ReceivedFromPhone/ShareToPhone folders
or the owner's own text history.

Deliberately kept simple and in-memory (rooms don't need to survive a
server restart - if the app restarts, in-progress rooms are gone, which
is a fine tradeoff for a personal tool being lent out temporarily). Room
FILES on disk are cleaned up by cleanup_expired(), called periodically
from web_server.py's background thread and opportunistically whenever a
new room is created.

Safety-relevant defaults live in config.py (rooms_enabled, defaults OFF;
room_max_age_hours; room_max_file_mb) since exposing an upload endpoint
to literally anyone with the link is a different risk profile than the
owner's own PIN-gated page.
"""

import secrets
import shutil
import threading
import time
from pathlib import Path

from config import BASE_DIR
from logger import get_logger

log = get_logger()

ROOMS_DIR = BASE_DIR / "rooms"
# Avoids visually-confusing characters (0/O, 1/l/I) since a room code
# might occasionally need to be typed rather than scanned.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

_lock = threading.Lock()
_rooms = {}  # code -> {"created_at": float, "last_activity": float, "texts": [dict, ...]}


def _generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def create_room() -> str:
    with _lock:
        code = _generate_code()
        while code in _rooms:  # astronomically unlikely, but be certain
            code = _generate_code()
        _rooms[code] = {"created_at": time.time(), "last_activity": time.time(), "texts": []}
    room_dir(code).mkdir(parents=True, exist_ok=True)
    log.info("Created room %s", code)
    return code


def room_exists(code: str) -> bool:
    return code in _rooms


def touch_room(code: str) -> None:
    if code in _rooms:
        _rooms[code]["last_activity"] = time.time()


def room_dir(code: str) -> Path:
    return ROOMS_DIR / code


def add_room_text(code: str, text: str) -> dict | None:
    if code not in _rooms:
        return None
    entry = {"id": len(_rooms[code]["texts"]) + 1, "text": text, "ts": time.time()}
    with _lock:
        _rooms[code]["texts"].append(entry)
        del _rooms[code]["texts"][:-100]  # cap history per room
    touch_room(code)
    return entry


def list_room_texts(code: str) -> list:
    if code not in _rooms:
        return []
    return list(_rooms[code]["texts"])


def list_active_rooms() -> list:
    """For the GUI's Shared Rooms tab: code, age, and approximate size on disk."""
    out = []
    for code, info in sorted(_rooms.items(), key=lambda kv: kv[1]["last_activity"], reverse=True):
        d = room_dir(code)
        size_mb = 0.0
        file_count = 0
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file():
                    size_mb += f.stat().st_size
                    file_count += 1
            size_mb /= (1024 * 1024)
        out.append({
            "code": code,
            "created_at": info["created_at"],
            "last_activity": info["last_activity"],
            "file_count": file_count,
            "size_mb": size_mb,
        })
    return out


def delete_room(code: str) -> None:
    with _lock:
        _rooms.pop(code, None)
    d = room_dir(code)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    log.info("Deleted room %s", code)


def delete_all_rooms() -> int:
    codes = list(_rooms.keys())
    for code in codes:
        delete_room(code)
    return len(codes)


def cleanup_expired(max_age_hours: float) -> int:
    """Delete rooms whose last activity is older than max_age_hours.
    Returns how many were removed. Safe to call often - cheap when
    there's nothing to do."""
    cutoff = time.time() - (max_age_hours * 3600)
    expired = [code for code, info in _rooms.items() if info["last_activity"] < cutoff]
    for code in expired:
        delete_room(code)
    if expired:
        log.info("Cleaned up %d expired room(s): %s", len(expired), ", ".join(expired))
    return len(expired)

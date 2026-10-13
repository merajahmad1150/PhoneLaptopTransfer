"""
core/room_manager.py
"Shared Rooms": someone with the link gets a private room (own folder, own text
feed) to pair THEIR laptop and phone, without touching your personal files.
Rooms live in memory; their files live under rooms\\ and are deleted when the
room expires.

v2.0 fixes / safety:
  * text ids come from a per-room counter (the old len()+1 id repeated after 100
    texts, so phones silently stopped receiving new text)
  * every access is under the lock
  * rooms\\ folders left over from a previous run are purged at startup
  * limits: max number of rooms, total bytes per room, text size, and a
    per-IP room-creation rate limit (anyone with the public link could
    otherwise create unlimited rooms)
"""

import secrets
import shutil
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from config import BASE_DIR
from logger import get_logger

log = get_logger()

ROOMS_DIR = BASE_DIR / "rooms"
# No look-alike characters (0/O, 1/I/L) since a code may occasionally be typed.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

_lock = threading.RLock()
_rooms = {}   # code -> {created_at,last_activity,texts,next_text_id,bytes}
_create_times = defaultdict(deque)   # ip -> timestamps of recent room creations


def _generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def purge_orphans() -> int:
    """Delete room folders that no longer belong to any live room (rooms are
    in memory, so after a restart every folder in rooms\\ is an orphan)."""
    n = 0
    if ROOMS_DIR.exists():
        for d in ROOMS_DIR.iterdir():
            if d.is_dir() and d.name not in _rooms:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
    if n:
        log.info("Removed %d leftover room folder(s) from a previous run", n)
    return n


def rate_limited(ip: str, per_minute: int = 5) -> bool:
    now = time.time()
    with _lock:
        q = _create_times[ip]
        while q and now - q[0] > 60:
            q.popleft()
        return len(q) >= per_minute


def create_room(ip: str = "?", max_rooms: int = 20):
    """Returns the new code, or None if the room limit is reached."""
    with _lock:
        if len(_rooms) >= max_rooms:
            log.warning("Room creation refused for %s: %d rooms already exist (limit %d)", ip, len(_rooms), max_rooms)
            return None
        code = _generate_code()
        while code in _rooms:
            code = _generate_code()
        now = time.time()
        _rooms[code] = {"created_at": now, "last_activity": now, "texts": [], "next_text_id": 1, "bytes": 0}
        _create_times[ip].append(now)
    room_dir(code).mkdir(parents=True, exist_ok=True)
    log.info("Created room %s (requested by %s)", code, ip)
    return code


def room_exists(code: str) -> bool:
    with _lock:
        return code in _rooms


def touch_room(code: str) -> None:
    with _lock:
        if code in _rooms:
            _rooms[code]["last_activity"] = time.time()


def room_dir(code: str) -> Path:
    return ROOMS_DIR / code


def room_bytes(code: str) -> int:
    with _lock:
        return _rooms[code]["bytes"] if code in _rooms else 0


def add_room_bytes(code: str, n: int) -> None:
    with _lock:
        if code in _rooms:
            _rooms[code]["bytes"] += n


def add_room_text(code: str, text: str):
    with _lock:
        if code not in _rooms:
            return None
        r = _rooms[code]
        entry = {"id": r["next_text_id"], "text": text, "ts": time.time()}
        r["next_text_id"] += 1
        r["texts"].append(entry)
        del r["texts"][:-100]
        r["last_activity"] = time.time()
        return entry


def list_room_texts(code: str, since: int = 0) -> list:
    with _lock:
        if code not in _rooms:
            return []
        return [e for e in _rooms[code]["texts"] if e["id"] > since]


def list_active_rooms() -> list:
    with _lock:
        snapshot = sorted(_rooms.items(), key=lambda kv: kv[1]["last_activity"], reverse=True)
        snapshot = [(c, dict(i)) for c, i in snapshot]
    out = []
    for code, info in snapshot:
        d = room_dir(code)
        size = 0
        count = 0
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file():
                    try:
                        size += f.stat().st_size
                    except OSError:
                        continue
                    count += 1
        out.append({"code": code, "created_at": info["created_at"], "last_activity": info["last_activity"],
                    "file_count": count, "size_mb": size / (1024 * 1024)})
    return out


def delete_room(code: str) -> None:
    with _lock:
        _rooms.pop(code, None)
    d = room_dir(code)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    log.info("Deleted room %s", code)


def delete_all_rooms() -> int:
    with _lock:
        codes = list(_rooms.keys())
    for code in codes:
        delete_room(code)
    return len(codes)


def cleanup_expired(max_age_hours: float) -> int:
    cutoff = time.time() - (max_age_hours * 3600)
    with _lock:
        expired = [c for c, i in _rooms.items() if i["last_activity"] < cutoff]
    for code in expired:
        delete_room(code)
    if expired:
        log.info("Cleaned up %d expired room(s): %s", len(expired), ", ".join(expired))
    return len(expired)

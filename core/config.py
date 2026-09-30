"""
core/config.py
Handles loading and saving persistent app settings (config.json).

Everything the app owns (config.json, logs/, and the default upload/share
folders) lives INSIDE the project folder itself - wherever you placed it -
rather than a separately hardcoded path. Earlier versions hardcoded
D:\\Tools\\PhoneLaptopTransfer\\ for app data regardless of where the
project was actually unzipped (e.g. D:\\Tools\\phone-laptop-transfer\\),
which created two unrelated folders. Tying BASE_DIR to __file__ means
there's only ever one folder, no matter what you name or where you put it.
"""

import json
from pathlib import Path

# core/config.py -> parent is "core/", parent.parent is the project root
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULTS = {
    "server_port": 8765,
    # Folder where files uploaded FROM the phone land on the laptop
    "download_folder": str(BASE_DIR / "ReceivedFromPhone"),
    # Folder the laptop exposes so the phone can browse/download files
    "share_folder": str(BASE_DIR / "ShareToPhone"),
    "adb_path": "adb",  # assumes adb is on PATH; user can override in Settings
    "syncthing_path": "syncthing",  # assumes on PATH; user can override
    "syncthing_web_ui": "http://127.0.0.1:8384",
    "scrcpy_path": "scrcpy",  # assumes on PATH; user can override in Settings
    # Conservative defaults for modest/older hardware (no dedicated GPU) -
    # a full-resolution phone mirror can be laggy to decode on integrated
    # graphics, so these keep it smooth rather than pretty by default.
    "scrcpy_max_size": 800,
    "scrcpy_bitrate_mbps": 4,
    "scrcpy_max_fps": 30,
    "scrcpy_turn_screen_off": False,
    # Points at the user's existing universal Tailscale Funnel publisher
    # (D:\Tools\tailscale-publisher\PUBLISH-TOOL.bat) - this app doesn't call
    # tailscale.exe itself, it hands off to that already-working tool so
    # every published tool goes through the same consistent script.
    "tailscale_publisher_path": r"D:\Tools\tailscale-publisher\PUBLISH-TOOL.bat",
    # Off by default (matches previous LAN-only behavior); the Public Access
    # tab strongly suggests turning this on before publishing to the internet.
    "require_access_pin": False,
    "access_pin": "",
    # Shared Rooms: lets strangers with the public link pair their OWN
    # laptop+phone via a private room, isolated from the owner's personal
    # share. Off by default - opening an upload endpoint to anyone with a
    # link is a different risk than the owner's own PIN-gated page, so this
    # is opt-in, with a size cap and auto-expiry as a safety net.
    "rooms_enabled": False,
    "room_max_age_hours": 24,
    "room_max_file_mb": 500,
    "last_tab": "transfer",
}


def ensure_dirs(cfg: dict) -> None:
    """Create the base dir + configured folders if they don't exist yet."""
    for key in ("download_folder", "share_folder"):
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load config.json, creating it with defaults on first run."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        cfg = dict(DEFAULTS)
        save_config(cfg)
        ensure_dirs(cfg)
        return cfg

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Backfill any missing keys (e.g. after an app upgrade added new settings)
        changed = False
        for k, v in DEFAULTS.items():
            if k not in cfg:
                cfg[k] = v
                changed = True
        if changed:
            save_config(cfg)
    except (json.JSONDecodeError, OSError):
        # Corrupt config: back it up and start fresh rather than crashing
        try:
            CONFIG_PATH.rename(CONFIG_PATH.with_suffix(".json.bak"))
        except OSError:
            pass
        cfg = dict(DEFAULTS)
        save_config(cfg)

    ensure_dirs(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def logs_dir() -> Path:
    d = BASE_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d

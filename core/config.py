"""
core/config.py
Loads and saves persistent settings (config.json) and defines every folder
the tool uses. EVERYTHING lives inside the project folder (wherever you put
it, e.g. D:\\Tools\\PhoneLaptopTransfer\\) so nothing is scattered across
drives and nothing is written to C:. That includes the temp folder used for
large uploads (BASE_DIR\\temp) - see run.py, which points Python's temp
directory there.

New keys added in later versions are back-filled automatically into an
existing config.json, so upgrading never loses your settings.
"""

import json
from pathlib import Path

# core/config.py -> parent is "core/", parent.parent is the project root
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULTS = {
    # ---- server ----
    "server_port": 8765,
    "bind_host": "0.0.0.0",
    "download_folder": str(BASE_DIR / "ReceivedFromPhone"),
    "share_folder": str(BASE_DIR / "ShareToPhone"),
    "text_folder": str(BASE_DIR / "ReceivedText"),
    "auto_start_server": True,
    # How the tool opens: "ask" (show the choice dialog every time),
    # "gui" (desktop window) or "web" (no window; control it from any browser
    # on the same Wi-Fi at /admin).
    "startup_mode": "ask",
    # ---- history / privacy of the phone page ----
    # Items disappear from the PHONE PAGE after this many hours, but stay saved
    # on the laptop (data/history.jsonl, ReceivedText/, ReceivedFromPhone/).
    # 0 = never hide.
    "frontend_visible_hours": 6,
    # ---- clipboard ----
    # Text sent from the phone over the LOCAL Wi-Fi is copied to the laptop
    # clipboard automatically (never for internet/public-link visitors).
    "auto_copy_text": True,
    # ---- GUI behaviour ----
    "right_click_pastes": True,
    "last_tab": "transfer",
    # ---- tools ----
    "adb_path": "adb",
    "syncthing_path": "syncthing",
    "syncthing_web_ui": "http://127.0.0.1:8384",
    "scrcpy_path": "scrcpy",
    "scrcpy_max_size": 800,
    "scrcpy_bitrate_mbps": 4,
    "scrcpy_max_fps": 30,
    "scrcpy_turn_screen_off": False,
    "uxplay_path": "",                # optional AirPlay receiver for iPhone mirroring (same Wi-Fi)
    # ---- public access (Tailscale Funnel) ----
    "tailscale_publisher_path": r"D:\Tools\tailscale-publisher\PUBLISH-TOOL.bat",
    "tailscale_exe": "",              # blank = auto-find (PATH + usual install folders)
    "auto_detect_public_url": True,   # watch Tailscale and show the live public URL by itself
    "public_url_manual": "",          # optional fallback if auto-detect can't see your publisher
    "require_access_pin": False,
    "access_pin": "",
    # ---- shared rooms ----
    "rooms_enabled": False,
    "room_max_age_hours": 24,
    "room_max_file_mb": 500,
    "room_max_total_mb": 2048,
    "room_max_rooms": 20,
    "room_max_text_kb": 256,
    # ---- speed tuning (see README "Transfer speed") ----
    "server_threads": 8,
    "parallel_uploads": 3,            # phone page uploads this many files at once
    "inbuf_overflow_mb": 128,         # uploads up to this size stay in RAM (no temp file)
    "socket_buffer_kb": 256,          # waitress recv/send chunk size
    "min_free_space_mb": 500,         # refuse uploads that would leave less than this free
    # ---- logs ----
    "log_keep_sessions": 500,
}

# Keys whose values must never be written to logs
SECRET_KEYS = ("access_pin",)


def redacted(cfg: dict) -> dict:
    """Copy of the config that is safe to print/log (PIN hidden)."""
    return {k: ("***hidden***" if k in SECRET_KEYS and v else v) for k, v in cfg.items()}


def data_dir() -> Path:
    d = BASE_DIR / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def temp_dir() -> Path:
    d = BASE_DIR / "temp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = BASE_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_dirs(cfg: dict) -> None:
    """Create every folder the tool uses if it doesn't exist yet."""
    for key in ("download_folder", "share_folder", "text_folder"):
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)
    data_dir()
    temp_dir()
    logs_dir()


def load_config() -> dict:
    """Load config.json, creating it with defaults on first run."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        cfg = dict(DEFAULTS)
        save_config(cfg)
        ensure_dirs(cfg)
        return cfg

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError("config.json is not a JSON object")
        changed = False
        for k, v in DEFAULTS.items():
            if k not in cfg:
                cfg[k] = v
                changed = True
        if changed:
            save_config(cfg)
    except (json.JSONDecodeError, OSError, ValueError):
        # Corrupt config: back it up and start fresh rather than crashing
        try:
            backup = CONFIG_PATH.with_suffix(".json.bak")
            if backup.exists():
                backup.unlink()
            CONFIG_PATH.rename(backup)
        except OSError:
            pass
        cfg = dict(DEFAULTS)
        save_config(cfg)

    ensure_dirs(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    """Atomic save (write to a temp file, then replace) so a crash or power
    cut mid-save can never leave a half-written config.json."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    tmp.replace(CONFIG_PATH)

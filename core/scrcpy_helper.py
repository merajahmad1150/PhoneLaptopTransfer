"""
core/scrcpy_helper.py
"See and control your phone from the laptop with the mouse" (mirror the
screen, open apps, drag files onto it, move/delete things with clicks)
is exactly what scrcpy already does - it's a free, open-source,
actively-maintained tool built for this over ADB. Rebuilding video
capture + H.264 decode + touch-injection from scratch would be a huge,
fragile undertaking to get right in one pass, so this app launches the
real tool instead of reinventing it.

scrcpy is a separate download (not bundled - it's a few MB per platform
and updates independently). See SETUP_GUIDE.md for where to get it.

What you get for free just by launching scrcpy, no extra code needed:
  - Full mouse control of the phone as if it were a touchscreen (open
    apps, tap, swipe, long-press)
  - Drag-and-drop a file (or an .apk) straight onto the scrcpy window to
    push it to the phone
  - Clipboard sync between PC and phone (Ctrl+C/Ctrl+V works across both)
So "copy a folder / move something / delete something" on the phone is
done by mirroring, then using a file manager app ON the phone through the
mirror - not a separate feature we build here.
"""

import shutil
import subprocess
import time
from pathlib import Path

from logger import get_logger

log = get_logger()


def is_installed(scrcpy_path: str) -> bool:
    """scrcpy_path may be a bare command (checked via PATH) or a full path
    to scrcpy.exe."""
    if Path(scrcpy_path).is_file():
        return True
    return shutil.which(scrcpy_path) is not None


def build_args(scrcpy_path: str, cfg: dict) -> list:
    """Build the scrcpy command line from the app's performance settings."""
    args = [scrcpy_path]
    max_size = cfg.get("scrcpy_max_size")
    if max_size:
        args += ["--max-size", str(int(max_size))]
    bitrate = cfg.get("scrcpy_bitrate_mbps")
    if bitrate:
        args += ["--video-bit-rate", f"{int(bitrate)}M"]
    max_fps = cfg.get("scrcpy_max_fps")
    if max_fps:
        args += ["--max-fps", str(int(max_fps))]
    if cfg.get("scrcpy_turn_screen_off"):
        args += ["--turn-screen-off"]
    return args


def launch(scrcpy_path: str, cfg: dict) -> tuple:
    """
    Start scrcpy as its own window (non-blocking - it runs until the user
    closes it). Returns (ok, message). Since scrcpy can fail immediately
    if no device is connected/authorized, we briefly check whether the
    process is still alive a moment after starting so that failure shows
    up as a message instead of a window that silently never appears.
    """
    if not is_installed(scrcpy_path):
        msg = f"'{scrcpy_path}' not found. Install scrcpy and set its path in Settings (see SETUP_GUIDE.md)."
        log.warning(msg)
        return False, msg

    args = build_args(scrcpy_path, cfg)
    log.info("Launching scrcpy: %s", " ".join(args))
    try:
        # scrcpy opens its OWN window (that's the point), so we don't
        # suppress window creation the way we do for headless CLI tools.
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError as exc:
        log.error("Failed to launch scrcpy: %s", exc, exc_info=True)
        return False, str(exc)

    time.sleep(1.5)  # give it a moment to fail fast if no device is attached
    if proc.poll() is not None:
        # Process already exited - almost certainly an error (no device,
        # unauthorized, etc). Grab whatever it printed to explain why.
        output = proc.stdout.read() if proc.stdout else ""
        log.error("scrcpy exited immediately (code %s): %s", proc.returncode, output)
        return False, output.strip() or f"scrcpy exited immediately (code {proc.returncode})"

    log.info("scrcpy window launched (pid %s)", proc.pid)
    return True, "scrcpy launched"

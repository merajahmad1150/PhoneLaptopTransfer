"""
core/adb_helper.py
Optional feature: direct file transfer to/from an Android phone via ADB
(Android Debug Bridge). Faster and more reliable than Wi-Fi for large
batches when the phone is plugged in via USB, or on wireless ADB.

Requires Android platform-tools (adb.exe) to be installed and either on
PATH or pointed to via cfg["adb_path"]. This module never assumes adb is
present - every function checks availability first and returns a clear
error instead of raising, so a missing/optional tool never crashes the app.
"""

import subprocess
import time
from pathlib import Path

from logger import get_logger

log = get_logger()

# Common destination folders on a typical Android phone, shown as quick picks
COMMON_PHONE_PATHS = [
    "/sdcard/Download",
    "/sdcard/DCIM/Camera",
    "/sdcard/Pictures",
    "/sdcard/Movies",
    "/sdcard/Music",
    "/sdcard/Documents",
]


def _run(cmd: list, timeout: int = None) -> subprocess.CompletedProcess:
    log.debug("Running command: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def check_adb_available(adb_path: str) -> tuple[bool, str]:
    """Returns (available, message)."""
    try:
        result = _run([adb_path, "version"], timeout=5)
        if result.returncode == 0:
            first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "adb"
            log.info("ADB available: %s", first_line)
            return True, first_line
        log.warning("adb version returned code %s: %s", result.returncode, result.stderr)
        return False, result.stderr.strip() or "adb returned a non-zero exit code"
    except FileNotFoundError:
        msg = f"'{adb_path}' not found. Install Android platform-tools or set the correct path in Settings."
        log.warning(msg)
        return False, msg
    except subprocess.TimeoutExpired:
        msg = "adb did not respond in time."
        log.warning(msg)
        return False, msg
    except OSError as exc:
        log.error("Unexpected error checking adb: %s", exc, exc_info=True)
        return False, str(exc)


def list_devices(adb_path: str) -> tuple[bool, list, str]:
    """Returns (ok, list_of_device_ids, message)."""
    try:
        result = _run([adb_path, "devices"], timeout=10)
    except FileNotFoundError:
        # Same expected, already-actionable condition as check_adb_available -
        # a full traceback here would just be noise in the log/GUI panel for
        # something the user can act on from a one-line message.
        msg = f"'{adb_path}' not found. Install Android platform-tools or set the correct path in Settings."
        log.warning(msg)
        return False, [], msg
    except subprocess.TimeoutExpired:
        msg = "adb did not respond in time."
        log.warning(msg)
        return False, [], msg
    except OSError as exc:
        # Genuinely unexpected (permissions, corrupted install, etc.) -
        # worth the full traceback here since it's not a known condition.
        log.error("Unexpected error listing adb devices: %s", exc, exc_info=True)
        return False, [], str(exc)

    if result.returncode != 0:
        return False, [], result.stderr.strip() or "adb devices failed"

    devices = []
    for line in result.stdout.strip().splitlines()[1:]:  # skip header line
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2 and parts[1] == "device":
            devices.append(parts[0])
    log.info("Found %d ADB device(s): %s", len(devices), devices)
    return True, devices, ""


def push(adb_path: str, local_path: str, remote_path: str, progress_cb=None) -> tuple[bool, str]:
    """
    Push a local file/folder to the phone. progress_cb(str) is called with
    each line of adb's own output (adb prints per-file progress for folders).
    """
    return _run_transfer([adb_path, "push", local_path, remote_path], progress_cb,
                          f"push '{local_path}' -> '{remote_path}'")


def pull(adb_path: str, remote_path: str, local_path: str, progress_cb=None) -> tuple[bool, str]:
    """Pull a file/folder from the phone to a local destination."""
    Path(local_path).mkdir(parents=True, exist_ok=True) if not Path(local_path).suffix else None
    return _run_transfer([adb_path, "pull", remote_path, local_path], progress_cb,
                          f"pull '{remote_path}' -> '{local_path}'")


def _run_transfer(cmd: list, progress_cb, description: str) -> tuple[bool, str]:
    log.info("Starting ADB transfer: %s", description)
    start = time.time()
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        msg = f"adb executable not found: {exc}"
        log.error(msg)
        return False, msg
    except OSError as exc:
        log.error("Failed to start adb transfer: %s", exc, exc_info=True)
        return False, str(exc)

    output_lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        output_lines.append(line)
        log.debug("adb: %s", line)
        if progress_cb:
            progress_cb(line)

    proc.wait()
    elapsed = time.time() - start
    full_output = "\n".join(output_lines)

    if proc.returncode == 0:
        log.info("ADB transfer finished in %.2fs: %s", elapsed, description)
        return True, full_output
    else:
        log.error("ADB transfer FAILED (code %s) after %.2fs: %s\n%s",
                   proc.returncode, elapsed, description, full_output)
        return False, full_output or f"adb exited with code {proc.returncode}"

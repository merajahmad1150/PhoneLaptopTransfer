"""
core/adb_helper.py
Optional: file transfer with an Android phone over ADB (USB or wireless), plus
WIRELESS QR PAIRING (Android 11+): the laptop shows a QR code, you scan it from
Developer options > Wireless debugging > "Pair device with QR code", tap Allow,
and the phone is paired and connected - then scrcpy mirrors its screen.

Every function checks that adb exists and returns a clear message instead of
raising, so a missing optional tool never crashes the app. All adb output is
decoded as UTF-8 with replacement (Urdu/Hindi file names can't crash a reader).
"""

import re
import secrets
import subprocess
import threading
import time
from pathlib import Path

from logger import get_logger

log = get_logger()

COMMON_PHONE_PATHS = [
    "/sdcard/Download", "/sdcard/DCIM/Camera", "/sdcard/Pictures",
    "/sdcard/Movies", "/sdcard/Music", "/sdcard/Documents",
]
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd: list, timeout: int = None) -> subprocess.CompletedProcess:
    log.debug("Running command: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=_FLAGS)


def check_adb_available(adb_path: str) -> tuple:
    """Returns (available, message)."""
    try:
        result = _run([adb_path, "version"], timeout=8)
        if result.returncode == 0:
            first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "adb"
            log.info("ADB available: %s", first)
            return True, first
        log.warning("adb version returned code %s: %s", result.returncode, result.stderr)
        return False, result.stderr.strip() or "adb returned a non-zero exit code"
    except FileNotFoundError:
        msg = f"'{adb_path}' not found. Install Android platform-tools or set the path in Settings."
        log.warning(msg)
        return False, msg
    except subprocess.TimeoutExpired:
        log.warning("adb did not respond in time.")
        return False, "adb did not respond in time."
    except OSError as exc:
        log.error("Unexpected error checking adb: %s", exc, exc_info=True)
        return False, str(exc)


def parse_devices(output: str) -> tuple:
    """-> (ready_serials, [(serial, state)] for devices that exist but can't be used yet)"""
    ready, other = [], []
    for line in output.strip().splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            (ready if parts[1] == "device" else other).append(parts[0] if parts[1] == "device" else (parts[0], parts[1]))
    return ready, other


def list_devices(adb_path: str) -> tuple:
    """Returns (ok, ready_device_ids, message). The message explains phones that
    are visible but not usable (unauthorized/offline) instead of hiding them."""
    try:
        result = _run([adb_path, "devices"], timeout=15)
    except FileNotFoundError:
        msg = f"'{adb_path}' not found. Install Android platform-tools or set the path in Settings."
        log.warning(msg)
        return False, [], msg
    except subprocess.TimeoutExpired:
        log.warning("adb did not respond in time.")
        return False, [], "adb did not respond in time."
    except OSError as exc:
        log.error("Unexpected error listing adb devices: %s", exc, exc_info=True)
        return False, [], str(exc)
    if result.returncode != 0:
        return False, [], result.stderr.strip() or "adb devices failed"
    ready, other = parse_devices(result.stdout)
    notes = []
    for serial, state in other:
        if state == "unauthorized":
            notes.append(f"{serial}: unlock the phone and tap 'Allow USB debugging' (tick 'Always allow')")
        elif state == "offline":
            notes.append(f"{serial}: offline - unplug/replug the cable or toggle USB debugging")
        else:
            notes.append(f"{serial}: state '{state}'")
    log.info("ADB devices ready: %s%s", ready or "none", f" | not usable: {notes}" if notes else "")
    return True, ready, "; ".join(notes)


def push(adb_path, local_path, remote_path, progress_cb=None) -> tuple:
    return _run_transfer([adb_path, "push", local_path, remote_path], progress_cb,
                         f"push '{local_path}' -> '{remote_path}'")


def pull(adb_path, remote_path, local_path, progress_cb=None) -> tuple:
    """`local_path` is always a destination FOLDER (the GUI uses a folder picker)."""
    try:
        Path(local_path).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"Cannot create destination folder: {exc}"
    return _run_transfer([adb_path, "pull", remote_path, local_path], progress_cb,
                         f"pull '{remote_path}' -> '{local_path}'")


def _run_transfer(cmd: list, progress_cb, description: str) -> tuple:
    log.info("Starting ADB transfer: %s", description)
    start = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", bufsize=1, creationflags=_FLAGS)
    except FileNotFoundError as exc:
        msg = f"adb executable not found: {exc}"
        log.error(msg)
        return False, msg
    except OSError as exc:
        log.error("Failed to start adb transfer: %s", exc, exc_info=True)
        return False, str(exc)
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        lines.append(line)
        log.debug("adb: %s", line)
        if progress_cb:
            progress_cb(line)
    proc.wait()
    elapsed = time.time() - start
    ok = proc.returncode == 0
    summary = lines[-1] if lines else ("done" if ok else "failed")
    (log.info if ok else log.error)("ADB transfer %s in %.1fs: %s", "finished" if ok else "FAILED", elapsed, summary)
    return ok, summary


# ---------------------------------------------------------------------- #
# Wireless debugging: QR pairing (Android 11+) and connect-by-address
# ---------------------------------------------------------------------- #
def new_pairing_credentials() -> tuple:
    """(service name, password) for one pairing attempt."""
    return "PLT-" + secrets.token_hex(3).upper(), "".join(secrets.choice("0123456789") for _ in range(8))


def pairing_qr_text(name: str, password: str) -> str:
    """The exact text Android's 'Pair device with QR code' scanner understands."""
    return f"WIFI:T:ADB;S:{name};P:{password};;"


def parse_mdns(output: str) -> list:
    """Parse `adb mdns services` -> [(name, service_type, 'ip:port')]"""
    out = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].startswith("_adb"):
            out.append((parts[0], parts[1].rstrip("."), parts[2]))
    return out


def pair_with_qr(adb_path: str, name: str, password: str, timeout: int = 150,
                 status_cb=None, cancel: threading.Event = None) -> tuple:
    """Waits for the phone to appear after it scanned the QR, pairs, connects.
    Returns (ok, message, serial_or_None). Runs in a worker thread."""
    say = status_cb or (lambda m: None)
    deadline = time.time() + timeout
    paired_addr = None
    say("Waiting for the phone to scan the QR code...")
    log.info("Wireless pairing: waiting for service '%s' (timeout %ds)", name, timeout)
    while time.time() < deadline and not (cancel and cancel.is_set()):
        try:
            res = _run([adb_path, "mdns", "services"], timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"adb mdns failed: {exc}", None
        services = parse_mdns(res.stdout)
        log.debug("mDNS services seen: %s", services)
        for sname, stype, addr in services:
            if stype == "_adb-tls-pairing._tcp" and sname == name:
                say(f"Phone found at {addr} - pairing...")
                pr = _run([adb_path, "pair", addr, password], timeout=40)
                text = (pr.stdout + pr.stderr).strip()
                log.info("adb pair result: %s", text)
                if "Successfully paired" in text:
                    paired_addr = addr.rsplit(":", 1)[0]
                    break
                return False, f"Pairing failed: {text or 'no answer from the phone'}", None
        if paired_addr:
            break
        time.sleep(2)
    if cancel and cancel.is_set():
        return False, "Cancelled.", None
    if not paired_addr:
        return False, ("The phone didn't show up. Make sure it is on the SAME Wi-Fi as this laptop, "
                       "Wireless debugging is ON, and you used 'Pair device with QR code'."), None
    say("Paired! Connecting...")
    serial = None
    for _ in range(20):          # Android needs a few seconds to publish its connect port
        if cancel and cancel.is_set():
            return False, "Cancelled.", None
        res = _run([adb_path, "mdns", "services"], timeout=15)
        for sname, stype, addr in parse_mdns(res.stdout):
            if stype == "_adb-tls-connect._tcp" and addr.startswith(paired_addr + ":"):
                cr = _run([adb_path, "connect", addr], timeout=20)
                log.info("adb connect %s: %s", addr, (cr.stdout + cr.stderr).strip())
                serial = addr
                break
        if serial:
            break
        time.sleep(1.5)
    if not serial:
        return True, "Paired, but the connect port wasn't announced yet. Press 'Refresh devices'.", None
    return True, f"Connected to {serial}", serial


def connect_address(adb_path: str, address: str) -> tuple:
    """`adb connect ip:port` - for a phone on another network reachable by IP
    (for example its Tailscale address)."""
    address = address.strip()
    if not re.match(r"^[\w.\-\[\]:]+:\d{2,5}$", address):
        return False, "Enter the address as ip:port, e.g. 100.101.102.103:5555"
    try:
        r = _run([adb_path, "connect", address], timeout=25)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"adb connect failed: {exc}"
    text = (r.stdout + r.stderr).strip()
    log.info("adb connect %s: %s", address, text)
    ok = "connected to" in text.lower() and "cannot" not in text.lower() and "failed" not in text.lower()
    return ok, text or "no answer"

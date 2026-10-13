"""
core/scrcpy_helper.py
Screen mirroring + mouse control of an ANDROID phone through scrcpy (free,
open-source), over USB or wireless ADB. Also an optional launcher for an
AirPlay receiver (UxPlay) so an iPhone can mirror to the laptop on the same
Wi-Fi. Mirror processes are tracked: their output is drained into the log
(the old version never read it, which could eventually freeze scrcpy) and
they are closed when the tool exits.
"""

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from logger import get_logger

log = get_logger()
_procs = []
_procs_lock = threading.Lock()


def _exists(path: str) -> bool:
    return bool(path) and (Path(path).is_file() or shutil.which(path) is not None)


def is_installed(scrcpy_path: str) -> bool:
    return _exists(scrcpy_path)


def build_args(scrcpy_path: str, cfg: dict, serial: str = None) -> list:
    args = [scrcpy_path]
    if serial:
        args += ["-s", serial]
    if cfg.get("scrcpy_max_size"):
        args += ["--max-size", str(int(cfg["scrcpy_max_size"]))]
    if cfg.get("scrcpy_bitrate_mbps"):
        args += ["--video-bit-rate", f"{int(cfg['scrcpy_bitrate_mbps'])}M"]
    if cfg.get("scrcpy_max_fps"):
        args += ["--max-fps", str(int(cfg["scrcpy_max_fps"]))]
    if cfg.get("scrcpy_turn_screen_off"):
        args += ["--turn-screen-off"]
    return args


def _drain(proc, tag: str):
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log.debug("%s: %s", tag, line[:300])
    except Exception:
        log.debug("%s output reader ended", tag, exc_info=True)


def _spawn(args: list, tag: str, env=None, wait_check: float = 1.5):
    """Start a GUI helper process, drain its output into the log, and report
    an immediate failure as a message. Returns (ok, message)."""
    log.info("Launching %s: %s", tag, " ".join(args))
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env)
    except OSError as exc:
        log.error("Failed to launch %s: %s", tag, exc, exc_info=True)
        return False, f"Could not start {tag}: {exc}"
    threading.Thread(target=_drain, args=(proc, tag), name=f"{tag}-output", daemon=True).start()
    time.sleep(wait_check)
    if proc.poll() is not None:
        log.error("%s exited immediately (code %s)", tag, proc.returncode)
        return False, (f"{tag} closed right away (exit code {proc.returncode}). "
                       f"Check the phone is connected/authorised - details are in the log.")
    with _procs_lock:
        _procs.append((tag, proc))
    log.info("%s is running (pid %s)", tag, proc.pid)
    return True, f"{tag} started."


def launch(scrcpy_path: str, cfg: dict, serial: str = None) -> tuple:
    if not is_installed(scrcpy_path):
        msg = f"'{scrcpy_path}' not found. Install scrcpy and set its path in Settings (see SETUP_GUIDE.md)."
        log.warning(msg)
        return False, msg
    env = dict(os.environ)
    adb = cfg.get("adb_path", "adb")
    if adb and adb != "adb" and Path(adb).is_file():
        env["ADB"] = adb     # make scrcpy use the SAME adb as this tool (avoids version-mismatch restarts)
    return _spawn(build_args(scrcpy_path, cfg, serial), "scrcpy", env=env)


def launch_airplay(uxplay_path: str) -> tuple:
    """Optional: start an AirPlay mirroring receiver for iPhone/iPad (same Wi-Fi)."""
    if not _exists(uxplay_path):
        return False, ("UxPlay (the AirPlay receiver) isn't set up. Put uxplay.exe somewhere and set "
                       "'uxplay_path' in config.json - see SETUP_GUIDE.md.")
    return _spawn([uxplay_path, "-n", "Laptop (PLT)"], "uxplay", wait_check=2.5)


def stop_all() -> None:
    with _procs_lock:
        items = list(_procs)
        _procs.clear()
    for tag, proc in items:
        if proc.poll() is None:
            log.info("Closing %s (pid %s)", tag, proc.pid)
            try:
                proc.terminate()
                proc.wait(timeout=4)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

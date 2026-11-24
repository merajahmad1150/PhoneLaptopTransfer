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
    # 0 / blank = no limit = the phone's NATIVE resolution (sharpest). Only pass the flag when limiting.
    if int(cfg.get("scrcpy_max_size") or 0) > 0:
        args += ["--max-size", str(int(cfg["scrcpy_max_size"]))]
    if cfg.get("scrcpy_bitrate_mbps"):
        args += ["--video-bit-rate", f"{int(cfg['scrcpy_bitrate_mbps'])}M"]
    if cfg.get("scrcpy_max_fps"):
        args += ["--max-fps", str(int(cfg["scrcpy_max_fps"]))]
    if cfg.get("scrcpy_turn_screen_off"):
        args += ["--turn-screen-off"]
    # Files dragged onto the mirror window go to the gallery folder (so Instagram/Gallery can see them)
    if cfg.get("phone_gallery_dir"):
        args += [f"--push-target={cfg['phone_gallery_dir'].rstrip('/')}/"]
    return args


def _drain(proc, tag: str, on_line=None):
    last = []
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log.debug("%s: %s", tag, line[:300])
                last = (last + [line])[-6:]
                if on_line:
                    try:
                        on_line(line)
                    except Exception:
                        log.debug("%s line callback failed", tag, exc_info=True)
    except Exception:
        log.debug("%s output reader ended", tag, exc_info=True)
    code = proc.wait()
    # Say WHY it ended (closed by you, phone unplugged, error) instead of going silent.
    log.info("%s ended (exit code %s)%s", tag, code, f" - last output: {' | '.join(last[-3:])[:300]}" if code else "")


def _spawn(args: list, tag: str, env=None, wait_check: float = 1.5, on_line=None):
    """Start a GUI helper process, drain its output into the log, and report
    an immediate failure as a message. Returns (ok, message)."""
    log.info("Launching %s: %s", tag, " ".join(args))
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env)
    except OSError as exc:
        log.error("Failed to launch %s: %s", tag, exc, exc_info=True)
        return False, f"Could not start {tag}: {exc}"
    threading.Thread(target=_drain, args=(proc, tag, on_line), name=f"{tag}-output", daemon=True).start()
    time.sleep(wait_check)
    if proc.poll() is not None:
        log.error("%s exited immediately (code %s)", tag, proc.returncode)
        return False, (f"{tag} closed right away (exit code {proc.returncode}). "
                       f"Check the phone is connected/authorised - details are in the log.")
    with _procs_lock:
        _procs.append((tag, proc))
    log.info("%s is running (pid %s)", tag, proc.pid)
    return True, f"{tag} started."


def launch(scrcpy_path: str, cfg: dict, serial: str = None, on_line=None) -> tuple:
    if not is_installed(scrcpy_path):
        msg = f"'{scrcpy_path}' not found. Install scrcpy and set its path in Settings (see SETUP_GUIDE.md)."
        log.warning(msg)
        return False, msg
    env = dict(os.environ)
    adb = cfg.get("adb_path", "adb")
    if adb and adb != "adb" and Path(adb).is_file():
        env["ADB"] = adb     # make scrcpy use the SAME adb as this tool (avoids version-mismatch restarts)
    # make sure the gallery folder exists so drag-and-drop transfers don't fail
    try:
        import adb_helper
        if cfg.get("phone_gallery_dir"):
            adb_helper.ensure_remote_dir(adb, cfg["phone_gallery_dir"], serial)
    except Exception:
        log.debug("Could not prepare the gallery folder", exc_info=True)
    return _spawn(build_args(scrcpy_path, cfg, serial), "scrcpy", env=env, on_line=on_line)


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

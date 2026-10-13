"""
core/public_url.py
Finds the tool's PUBLIC address by itself - no pasting, no "Show QR" button.

How: you publish the tool's local port with your own Tailscale script/command
(any way you like). This module asks the local Tailscale client what it is
currently publishing ("tailscale serve status --json", falling back to the
text output of "tailscale funnel status"), finds the entry that forwards to
THIS tool's port, and reports the https:// address (with the right port such
as :8443) plus whether it is a public Funnel or tailnet-only.

A background watcher re-checks every few seconds, so the public URL and its QR
code appear on their own whenever you publish - before or after starting the
tool - and disappear when you unpublish.

If Tailscale can't be found/read, a manually saved URL (Settings) is used as a
fallback, and everything is logged (raw Tailscale output is logged whenever it
changes) so detection problems can be diagnosed from the session log.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from logger import get_logger

log = get_logger()

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "0.0.0.0"}


# ---------------------------------------------------------------------- #
# Parsing (pure functions - unit tested)
# ---------------------------------------------------------------------- #
def _proxy_port(target: str):
    """'http://127.0.0.1:8765', '127.0.0.1:8765', 'localhost:8765/x' -> (host, port)"""
    t = (target or "").strip()
    t = re.sub(r"^[a-z+]+://", "", t, flags=re.I)
    t = t.split("/", 1)[0]
    m = re.match(r"^(\[[^\]]+\]|[^:]+):(\d+)$", t)
    if not m:
        return None, None
    return m.group(1).lower(), int(m.group(2))


def _make_url(hostport: str) -> str:
    host, _, port = hostport.rpartition(":")
    if not host:
        return f"https://{hostport}/"
    return f"https://{host}/" if port == "443" else f"https://{host}:{port}/"


def parse_serve_json(text: str, local_port: int):
    """Returns (url, is_funnel) or None, from `tailscale serve status --json`."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    web = data.get("Web") or {}
    funnel = data.get("AllowFunnel") or {}
    matches = []
    for hostport, cfg in web.items():
        handlers = (cfg or {}).get("Handlers") or {}
        for _path, h in handlers.items():
            host, port = _proxy_port((h or {}).get("Proxy", ""))
            if port == local_port and host in _LOCAL_HOSTS:
                matches.append((hostport, bool(funnel.get(hostport))))
                break
    if not matches:
        return None
    matches.sort(key=lambda m: not m[1])   # public (Funnel) entries first
    hostport, is_funnel = matches[0]
    return _make_url(hostport), is_funnel


def parse_status_text(text: str, local_port: int):
    """Returns (url, is_funnel) or None, from the plain-text output of
    `tailscale funnel status` / `tailscale serve status`."""
    if not text:
        return None
    current = None  # (url, is_funnel)
    found = []
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^(https?://\S+?)/?\s*\((Funnel on|tailnet only|Funnel off)[^)]*\)", line, re.I)
        if m:
            current = (m.group(1).rstrip("/") + "/", m.group(2).lower() == "funnel on")
            continue
        if current and "proxy" in line:
            m2 = re.search(r"proxy\s+(\S+)", line)
            if m2:
                host, port = _proxy_port(m2.group(1))
                if port == local_port and host in _LOCAL_HOSTS:
                    found.append(current)
    if not found:
        return None
    found.sort(key=lambda m: not m[1])
    return found[0]


# ---------------------------------------------------------------------- #
# Talking to the tailscale CLI
# ---------------------------------------------------------------------- #
def find_tailscale(configured: str = ""):
    candidates = []
    if configured:
        candidates.append(configured)
    which = shutil.which("tailscale")
    if which:
        candidates.append(which)
    for base in (r"C:\Program Files\Tailscale", r"C:\Program Files (x86)\Tailscale",
                 r"D:\Apps\Tailscale", r"D:\Tools\Tailscale", r"D:\Program Files\Tailscale"):
        candidates.append(str(Path(base) / "tailscale.exe"))
    for c in candidates:
        try:
            if c and Path(c).is_file():
                return c
        except OSError:
            continue
    return None


def _run(args, timeout=8) -> tuple:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except OSError as exc:
        return 127, "", str(exc)
    return (r.returncode,
            r.stdout.decode("utf-8", "replace"),
            r.stderr.decode("utf-8", "replace"))


def detect(exe: str, local_port: int):
    """Returns (result, raw_note). result = (url, is_funnel) or None."""
    rc, out, err = _run([exe, "serve", "status", "--json"])
    if rc == 0:
        res = parse_serve_json(out, local_port)
        if res:
            return res, "serve status --json"
    notes = [f"serve --json rc={rc}: {(out or err).strip()[:300]}"]
    for sub in ("funnel", "serve"):
        rc2, out2, err2 = _run([exe, sub, "status"])
        res = parse_status_text(out2 + "\n" + err2, local_port)
        if res:
            return res, f"{sub} status (text)"
        notes.append(f"{sub} status rc={rc2}: {(out2 or err2).strip()[:300]}")
    return None, " | ".join(notes)


# ---------------------------------------------------------------------- #
# Watcher
# ---------------------------------------------------------------------- #
class PublicUrlWatcher:
    """Keeps `state` up to date:
        url        - https://host[:port]/ or ""
        is_funnel  - True when reachable from the whole internet
        source     - "auto" | "manual" | ""
        message    - short human-readable status for the GUI/dashboard
    """

    def __init__(self, cfg: dict, interval: float = 10.0):
        self.cfg = cfg
        self.interval = interval
        self.state = {"url": "", "is_funnel": False, "source": "", "message": "Starting..."}
        self._callbacks = []
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._thread = None
        self._exe = None
        self._exe_checked_at = 0.0
        self._last_note = None
        self._warned_missing = False

    def on_change(self, cb):
        self._callbacks.append(cb)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="PublicUrlWatcher", daemon=True)
        self._thread.start()
        log.info("Public URL watcher started (auto-detect %s, checks every %ds)",
                 "ON" if self.cfg.get("auto_detect_public_url", True) else "OFF", int(self.interval))

    def stop(self):
        self._stop.set()
        self._kick.set()

    def refresh_now(self):
        self._kick.set()

    def _set(self, **new):
        old = dict(self.state)
        self.state.update(new)
        if self.state != old:
            log.info("Public access: %s%s", self.state["message"],
                     f"  -> {self.state['url']}" if self.state["url"] else "")
            for cb in list(self._callbacks):
                try:
                    cb(dict(self.state))
                except Exception:
                    log.error("Public URL listener failed", exc_info=True)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._check_once()
            except Exception:
                log.error("Public URL check crashed (will retry)", exc_info=True)
            self._kick.wait(self.interval)
            self._kick.clear()

    def _manual_state(self, why: str):
        manual = (self.cfg.get("public_url_manual") or "").strip()
        if manual:
            if not manual.startswith("http"):
                manual = "https://" + manual
            self._set(url=manual, is_funnel=True, source="manual",
                      message=f"Using your saved link ({why})")
        else:
            self._set(url="", is_funnel=False, source="", message=why)

    def _check_once(self):
        port = int(self.cfg.get("server_port", 8765))
        if not self.cfg.get("auto_detect_public_url", True):
            return self._manual_state("auto-detect is turned off")

        if self._exe is None and time.time() - self._exe_checked_at > 60:
            self._exe_checked_at = time.time()
            self._exe = find_tailscale(self.cfg.get("tailscale_exe", ""))
            if self._exe:
                log.info("Tailscale found: %s", self._exe)
                self._warned_missing = False
            elif not self._warned_missing:
                log.warning("Tailscale was not found (looked on PATH and in the usual folders). "
                            "Set 'tailscale_exe' in config.json if it is installed somewhere else.")
                self._warned_missing = True
        if not self._exe:
            return self._manual_state("Tailscale not found on this PC")

        res, note = detect(self._exe, port)
        if not res and note != self._last_note:
            log.debug("Tailscale detection note (nothing published for port %s): %s", port, note)
        self._last_note = note
        if res:
            url, is_funnel = res
            self._set(url=url, is_funnel=is_funnel, source="auto",
                      message="LIVE on the internet (Funnel)" if is_funnel
                      else "Published on your tailnet only (Funnel is off)")
        else:
            self._manual_state(f"Not published yet - publish local port {port} with Tailscale "
                               f"and it will appear here automatically")

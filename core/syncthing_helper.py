"""
core/syncthing_helper.py
Optional feature: convenience launcher for Syncthing, a free open-source tool
that keeps folders continuously in sync between phone and laptop in the
background (no manual transfer needed once paired).

This module does NOT reimplement Syncthing - it's a separate program the
user installs once. We just detect it, offer to open its web UI for setup,
and point to the download page if it's missing. This keeps the feature
genuinely optional and doesn't add a heavy dependency to this app.
"""

import shutil
import subprocess
import webbrowser

from logger import get_logger

log = get_logger()

DOWNLOAD_PAGE = "https://syncthing.net/downloads/"
ANDROID_APP_INFO = "https://syncthing.net/downloads/ (Syncthing app is also on F-Droid / Google Play)"


def is_installed(syncthing_path: str) -> bool:
    """Check if the syncthing executable can be found (on PATH or given path)."""
    found = shutil.which(syncthing_path) is not None
    log.debug("Syncthing installed check for '%s': %s", syncthing_path, found)
    return found


def launch_if_not_running(syncthing_path: str) -> tuple[bool, str]:
    """
    Attempt to start the syncthing background process. Safe to call even if
    it's already running (it will just fail to bind its port, which we
    treat as 'already running' rather than an error).
    """
    if not is_installed(syncthing_path):
        msg = "Syncthing is not installed or not on PATH."
        log.warning(msg)
        return False, msg
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.Popen(
            [syncthing_path, "-no-browser"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        log.info("Launched Syncthing background process")
        return True, "Syncthing launched"
    except OSError as exc:
        log.error("Failed to launch Syncthing: %s", exc, exc_info=True)
        return False, str(exc)


def open_web_ui(web_ui_url: str) -> None:
    log.info("Opening Syncthing web UI: %s", web_ui_url)
    webbrowser.open(web_ui_url)


def open_download_page() -> None:
    log.info("Opening Syncthing download page")
    webbrowser.open(DOWNLOAD_PAGE)

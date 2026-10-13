"""
core/web_mode.py
"Web mode": no desktop window. The server runs in this console and the whole
tool is controlled from a browser at  http://<laptop>:<port>/admin  (local
network only). Closing the console, Ctrl+C, or the dashboard's "Quit" button
stops it cleanly.
"""

import threading
import time
import webbrowser

import net_utils
from logger import get_logger
from qr_helper import make_qr_text
from version import APP_NAME, VERSION

log = get_logger()


def run(cfg: dict, server) -> int:
    stop = threading.Event()
    server.on_quit_requested(stop.set)

    try:
        server.start()
    except OSError as exc:
        log.error("Cannot start the server: %s", exc)
        print(f"\nCould not start on port {cfg['server_port']}: {exc}\n"
              "Another program (or another copy of this tool) is probably using that port.\n"
              "Close it, or change 'server_port' in config.json.")
        return 2

    port = cfg["server_port"]
    lan = f"http://{net_utils.get_local_ip()}:{port}"
    admin = f"{lan}/admin"
    banner = [
        "", "=" * 74,
        f"  {APP_NAME} v{VERSION}  -  WEB MODE",
        "=" * 74,
        f"  Phone page      : {lan}",
        f"  Control panel   : {admin}   (same Wi-Fi only)",
        f"  On this laptop  : http://127.0.0.1:{port}/admin",
        "  Public link     : shows up in the control panel by itself once you publish",
        f"                    local port {port} with Tailscale",
        "  Stop            : press Ctrl+C here, or use 'Quit' in the control panel",
        "=" * 74, "",
    ]
    print("\n".join(banner))
    try:
        print("Scan with your phone:\n")
        print(make_qr_text(lan))
    except Exception:
        log.debug("Could not draw the console QR code", exc_info=True)
    try:
        webbrowser.open(f"http://127.0.0.1:{port}/admin")
    except Exception:
        log.debug("Could not open the browser", exc_info=True)

    try:
        while not stop.wait(1.0):
            pass
        log.info("Quit requested - shutting down web mode")
    except KeyboardInterrupt:
        log.info("Ctrl+C pressed - shutting down web mode")
    finally:
        server.stop()
        time.sleep(0.2)
    return 0

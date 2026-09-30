"""
core/net_utils.py
Small helper to find the laptop's LAN IP address, so we can build a URL
the phone can actually reach on the same Wi-Fi network.
"""

import socket

from logger import get_logger

log = get_logger()


def get_local_ip() -> str:
    """
    Best-effort detection of the LAN IP address other devices would use to
    reach this machine. Uses a UDP 'connect' trick (no packets are actually
    sent) which works even with no default gateway configured for DNS.
    Falls back to 127.0.0.1 if nothing else works (transfer will then only
    work from the same machine, which we log clearly so it's not a silent
    failure).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        log.debug("Detected LAN IP via UDP trick: %s", ip)
        return ip
    except OSError as exc:
        log.warning("Could not detect LAN IP via UDP trick (%s); falling back to hostname lookup", exc)
        try:
            ip = socket.gethostbyname(socket.gethostname())
            log.debug("Detected LAN IP via hostname lookup: %s", ip)
            return ip
        except OSError as exc2:
            log.error("Could not detect any LAN IP (%s); falling back to 127.0.0.1 (phone won't reach this)", exc2)
            return "127.0.0.1"
    finally:
        s.close()

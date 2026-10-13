"""
core/net_utils.py
Finds the laptop's LAN IP (so the phone can reach it) and classifies
requests as "local network" or "internet/tunnel".
"""

import ipaddress
import socket
import time

from logger import get_logger

log = get_logger()

_cache = {"ip": None, "ts": 0.0}


def get_local_ip(max_age: float = 15.0) -> str:
    """Best-effort LAN IP. Cached for a few seconds and logged only when it
    CHANGES (the old version logged the same line dozens of times)."""
    now = time.time()
    if _cache["ip"] and now - _cache["ts"] < max_age:
        return _cache["ip"]
    ip = _detect()
    if ip != _cache["ip"]:
        log.info("LAN IP address: %s%s", ip, f" (was {_cache['ip']})" if _cache["ip"] else "")
    _cache.update(ip=ip, ts=now)
    return ip


def _detect() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packet is sent; just picks the outgoing interface
        return s.getsockname()[0]
    except OSError as exc:
        log.warning("Could not detect LAN IP via UDP trick (%s); trying hostname lookup", exc)
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError as exc2:
            log.error("Could not detect any LAN IP (%s); using 127.0.0.1 (phones cannot reach this)", exc2)
            return "127.0.0.1"
    finally:
        s.close()


def is_lan_address(addr: str) -> bool:
    """True for loopback and private-range addresses (192.168.x.x, 10.x.x.x,
    172.16-31.x.x, link-local). Tailscale's 100.64.0.0/10 range and public IPs
    are NOT local."""
    try:
        ip = ipaddress.ip_address((addr or "").strip())
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local

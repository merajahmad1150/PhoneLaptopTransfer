"""
core/clipboard_helper.py
Puts text on the Windows clipboard from ANY thread (the web server thread
calls this the moment text arrives from the phone), without needing the Tk
window. Uses the Win32 API directly with Unicode, so Urdu/Hindi/emoji text
is copied exactly. Retries because another app may be holding the clipboard
for a moment.

On non-Windows systems (only used when testing) it reports "unsupported".
"""

import sys
import time

from logger import get_logger

log = get_logger()

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def copy_text(text: str, retries: int = 15) -> bool:
    """Returns True if the text is now on the clipboard."""
    if sys.platform != "win32":
        log.debug("Clipboard copy skipped: not running on Windows")
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        # Windows apps expect CRLF line endings on the clipboard.
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        data = (normalized + "\0").encode("utf-16-le")

        opened = False
        for attempt in range(1, retries + 1):
            if user32.OpenClipboard(None):
                opened = True
                break
            log.debug("Clipboard busy (attempt %d/%d), retrying...", attempt, retries)
            time.sleep(0.05)
        if not opened:
            log.warning("Could not open the clipboard - another program is holding it")
            return False
        try:
            handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
            if not handle:
                log.error("GlobalAlloc failed for %d bytes (error %s)", len(data), ctypes.get_last_error())
                return False
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                kernel32.GlobalFree(handle)
                log.error("GlobalLock failed (error %s)", ctypes.get_last_error())
                return False
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            user32.EmptyClipboard()
            if not user32.SetClipboardData(_CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                log.error("SetClipboardData failed (error %s)", ctypes.get_last_error())
                return False
            # On success the system owns the memory - we must not free it.
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        log.error("Clipboard copy crashed", exc_info=True)
        return False

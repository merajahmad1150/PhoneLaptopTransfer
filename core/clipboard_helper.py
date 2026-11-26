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


# ---------------------------------------------------------------------- #
# Files and pictures (for the Clip Shelf and for pasting screenshots)
# ---------------------------------------------------------------------- #
def _set_clipboard_data(fmt: int, data: bytes, retries: int = 15) -> bool:
    """Put raw bytes on the clipboard in clipboard format `fmt` (Windows only)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        for _ in range(retries):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            log.warning("Could not open the clipboard - another program is holding it")
            return False
        try:
            handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
            ptr = kernel32.GlobalLock(handle) if handle else None
            if not ptr:
                if handle:
                    kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            user32.EmptyClipboard()
            if not user32.SetClipboardData(fmt, handle):
                kernel32.GlobalFree(handle)
                return False
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        log.error("Clipboard write (format %s) crashed", fmt, exc_info=True)
        return False


def copy_files(paths) -> bool:
    """Put files on the clipboard like Explorer's Ctrl+C, so Ctrl+V in Explorer/WhatsApp/Instagram pastes the files."""
    import struct
    paths = [str(p) for p in paths]
    if not paths:
        return False
    blob = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)          # DROPFILES: offset 20, point 0,0, not NC, wide chars
    ok = _set_clipboard_data(15, header + blob)               # CF_HDROP
    log.debug("Clipboard: %d file(s) copied -> %s", len(paths), ok)
    return ok


def copy_image(img) -> bool:
    """Put a PIL image on the clipboard as a bitmap (pastes into Paint, WhatsApp Web, Instagram web, Word...)."""
    import io
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    ok = _set_clipboard_data(8, buf.getvalue()[14:])          # CF_DIB = BMP without its 14-byte file header
    log.debug("Clipboard: image %sx%s copied -> %s", img.width, img.height, ok)
    return ok


def grab_image_or_files():
    """What is on the clipboard besides text? -> ("image", PIL.Image) | ("files", [paths]) | (None, None).
    A Win+Shift+S screenshot is an image; files copied in Explorer are a file list."""
    try:
        from PIL import ImageGrab
    except Exception:
        return None, None
    got = None
    for attempt in range(1, 9):
        try:
            got = ImageGrab.grabclipboard()
            break
        except OSError as exc:
            # "failed to open clipboard": the Snipping Tool (or another program) is still holding it - wait a moment.
            log.debug("Clipboard busy (attempt %d/8): %s", attempt, exc)
            time.sleep(0.1)
        except Exception:
            log.debug("Could not read an image from the clipboard", exc_info=True)
            return None, None
    else:
        log.warning("The clipboard stayed locked by another program - try again in a second")
        return None, None
    if got is None:
        return None, None
    if isinstance(got, (list, tuple)):
        return "files", [str(p) for p in got]
    return "image", got

"""
core/win_helpers.py
Small Windows-only helpers used by the Clip Shelf (all guarded: on any problem they log and the shelf still works):

  * set_noactivate(window)  - clicking the shelf does NOT steal keyboard focus from the app you are typing in
                              (otherwise 'paste into the active app' could not work)
  * send_ctrl_v()           - presses Ctrl+V in whatever window has focus
  * Hotkeys                 - global shortcuts (e.g. Ctrl+Alt+V shows/hides the shelf from anywhere)
  * single_instance(name)   - only one shelf at a time (named mutex)
"""

import queue
import sys
import threading
import time

from logger import get_logger

log = get_logger()

MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}


def parse_hotkey(text: str):
    """'ctrl+alt+v' -> (modifiers, virtual-key) or None if it cannot be understood."""
    parts = [p.strip().lower() for p in (text or "").split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p not in MOD:
            return None
        mods |= MOD[p]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key == "space":
        vk = 0x20
    else:
        return None
    return mods, vk


def set_noactivate(window, enable: bool = True) -> bool:
    """Make a Tk window 'no-activate' + tool window (no taskbar button)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        window.update_idletasks()
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
        user32.GetWindowLongW.restype = ctypes.c_long
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) if enable else (style & ~WS_EX_NOACTIVATE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        # SWP_NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|FRAMECHANGED
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)
        return True
    except Exception:
        log.warning("Could not change the shelf's focus behaviour", exc_info=True)
        return False


def send_ctrl_v() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        ke = ctypes.windll.user32.keybd_event
        ke(0x11, 0, 0, 0)          # Ctrl down
        ke(0x56, 0, 0, 0)          # V down
        ke(0x56, 0, 2, 0)          # V up
        ke(0x11, 0, 2, 0)          # Ctrl up
        return True
    except Exception:
        log.warning("Could not send Ctrl+V", exc_info=True)
        return False


class Hotkeys:
    """Global hotkeys on a tiny background thread; presses are put in a queue (poll() from the UI thread)."""

    def __init__(self):
        self.events = queue.Queue()
        self._thread = None
        self._tid = None
        self._map = {}

    def start(self, bindings: dict) -> None:
        """bindings: {'ctrl+alt+v': 'toggle', ...}"""
        if sys.platform != "win32" or self._thread:
            return
        self._map = {}
        parsed = []
        for text, action in bindings.items():
            p = parse_hotkey(text)
            if not p:
                log.warning("Hotkey '%s' is not valid (example: ctrl+alt+v) - ignored", text)
                continue
            self._map[len(parsed) + 1] = action
            parsed.append((len(parsed) + 1, p, text))
        if not parsed:
            return
        self._thread = threading.Thread(target=self._loop, args=(parsed,), name="Hotkeys", daemon=True)
        self._thread.start()

    def _loop(self, parsed):
        try:
            import ctypes
            from ctypes import wintypes
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            self._tid = kernel32.GetCurrentThreadId()
            for hid, (mods, vk), text in parsed:
                ok = user32.RegisterHotKey(None, hid, mods | 0x4000, vk)      # 0x4000 = no auto-repeat
                log.info("Hotkey %s %s", text, "registered" if ok else "could NOT be registered (another program uses it)")
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:                                         # WM_HOTKEY
                    self.events.put(self._map.get(msg.wParam))
            for hid, _, _ in parsed:
                user32.UnregisterHotKey(None, hid)
        except Exception:
            log.error("Hotkey thread crashed", exc_info=True)

    def poll(self):
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        if self._tid and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)    # WM_QUIT
            except Exception:
                pass


_mutex_handles = []


def single_instance(name: str) -> bool:
    """True if this is the first instance with that name."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.CreateMutexW(None, False, f"Local\\{name}")
        _mutex_handles.append(h)
        return k.GetLastError() != 183       # ERROR_ALREADY_EXISTS
    except Exception:
        return True

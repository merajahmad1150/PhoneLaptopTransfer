"""
core/dnd.py
Drag-and-drop with real Windows files/text (needs the small 'tkinterdnd2' package; Start.bat installs it).
If it is missing everything else still works - dropping is simply disabled and one line in the log says so.

   make_root()                   - the main window, with the drop engine loaded when available
   is_ready(widget)              - can this widget be a drop target / drag source?
   drop_target(widget, files_cb, text_cb)
   drag_source(widget, payload_cb)   payload_cb(event) -> ("files", [paths]) | ("text", "string") | None
"""

from logger import get_logger

log = get_logger()
DND_FILES, DND_TEXT = "DND_Files", "DND_Text"


def make_root():
    """-> (root, dnd_available)"""
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
        log.info("Drag-and-drop engine (tkinterdnd2) loaded")
        return root, True
    except Exception as exc:
        import tkinter as tk
        log.warning("Drag-and-drop engine not available (%s). Dropping files onto windows is disabled; everything else works. "
                    "Run Start.bat again to install 'tkinterdnd2'.", exc)
        return tk.Tk(), False


def is_ready(widget) -> bool:
    return hasattr(widget, "drop_target_register") and hasattr(widget, "dnd_bind")


def drop_target(widget, files_cb=None, text_cb=None, hover_cb=None) -> bool:
    if not is_ready(widget):
        return False
    try:
        types = []
        if files_cb:
            types.append(DND_FILES)
        if text_cb:
            types.append(DND_TEXT)
        widget.drop_target_register(*types)

        def on_drop(event):
            data = event.data or ""
            try:
                paths = [p for p in widget.tk.splitlist(data)]
            except Exception:
                paths = [data]
            import os
            if files_cb and paths and all(os.path.exists(p) for p in paths):
                files_cb(paths)
            elif text_cb:
                text_cb(data)
            return "copy"

        def on_enter(event):
            if hover_cb:
                hover_cb(True)
            return "copy"

        def on_leave(event):
            if hover_cb:
                hover_cb(False)
            return "copy"

        def on_drop_done(event):
            if hover_cb:
                hover_cb(False)
            return on_drop(event)

        widget.dnd_bind("<<Drop>>", on_drop_done)
        if hover_cb:
            widget.dnd_bind("<<DropEnter>>", on_enter)
            widget.dnd_bind("<<DropLeave>>", on_leave)
        return True
    except Exception:
        log.warning("Could not enable dropping on %s", widget, exc_info=True)
        return False


def drag_source(widget, payload_cb) -> bool:
    if not is_ready(widget):
        return False
    try:
        widget.drag_source_register(1, DND_TEXT, DND_FILES)

        def on_init(event):
            payload = payload_cb(event)
            if not payload:
                return "break"
            kind, value = payload
            if kind == "files":
                tcl = " ".join("{%s}" % p if " " in p else p for p in value)
                return ("copy", DND_FILES, tcl)
            return ("copy", DND_TEXT, value)

        widget.dnd_bind("<<DragInitCmd>>", on_init)
        return True
    except Exception:
        log.warning("Could not enable dragging from %s", widget, exc_info=True)
        return False


def row_at_pointer(listbox, event):
    """Index of the list row under the mouse, or None. tkinterdnd2 drag events have no .x/.y, only screen
    coordinates (x_root/y_root) - the shelf failed with "'DnDEvent' object has no attribute 'y'" because of that."""
    try:
        y_root = getattr(event, "y_root", None)
        if y_root is None:
            y_root = listbox.winfo_pointery()
        y = y_root - listbox.winfo_rooty()
        idx = listbox.nearest(y)
        if not (0 <= idx < listbox.size()):
            return None
        box = listbox.bbox(idx)
        if box and not (box[1] <= y <= box[1] + box[3]):
            return None                        # pointer is in the empty space below the last row
        listbox.selection_clear(0, "end")
        listbox.selection_set(idx)
        return idx
    except Exception:
        log.debug("Could not find the row being dragged", exc_info=True)
        return None

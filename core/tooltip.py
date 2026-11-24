"""
core/tooltip.py
Hover explanations (requirement: point at any button/icon and a few lines explain it).
One tiny tooltip window is reused for the whole program, so it costs almost no memory.
"""

import tkinter as tk

_tip = {"win": None, "label": None, "after": None}


def _hide(_event=None):
    if _tip["after"]:
        try:
            _tip["win"].after_cancel(_tip["after"])
        except Exception:
            pass
        _tip["after"] = None
    if _tip["win"] is not None:
        try:
            _tip["win"].withdraw()
        except tk.TclError:
            _tip["win"] = None


def _show(widget, text, x, y):
    if _tip["win"] is None:
        w = tk.Toplevel(widget)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        lbl = tk.Label(w, justify="left", bg="#fff7d6", fg="#2b2540", relief="solid", bd=1, padx=7, pady=4,
                       font=("Segoe UI", 9), wraplength=300)
        lbl.pack()
        _tip["win"], _tip["label"] = w, lbl
    _tip["label"].configure(text=text)
    w = _tip["win"]
    w.update_idletasks()
    sw = w.winfo_screenwidth()
    px = min(x + 14, sw - w.winfo_reqwidth() - 8)
    w.geometry(f"+{max(px, 0)}+{y + 18}")
    w.deiconify()


def add_tooltip(widget, text: str, delay: int = 550) -> None:
    """Show `text` when the mouse rests on `widget`."""
    if not text:
        return

    def enter(event):
        _hide()
        _tip["after"] = widget.after(delay, lambda: _show(widget, text, event.x_root, event.y_root))

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")


def add_canvas_tip(canvas, tag: str, text: str, delay: int = 450) -> None:
    """Tooltip for one drawn item (tag) on a Canvas, e.g. the gear icon in the header."""
    def enter(event):
        _hide()
        canvas.configure(cursor="hand2")
        _tip["after"] = canvas.after(delay, lambda: _show(canvas, text, event.x_root, event.y_root))

    def leave(_event):
        _hide()
        canvas.configure(cursor="")
    canvas.tag_bind(tag, "<Enter>", enter)
    canvas.tag_bind(tag, "<Leave>", leave)


def attach_tooltips(root, tips: list) -> int:
    """Walk the widget tree; for every button/checkbox/radio whose text contains one of the keys, add its tip.
    tips: [(text fragment, explanation), ...]. Returns how many widgets got a tooltip."""
    count = 0
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            stack.extend(w.winfo_children())
            text = str(w.cget("text")) if "text" in w.keys() else ""
        except Exception:
            continue
        if not text:
            continue
        low = text.lower()
        for fragment, tip in tips:
            if fragment.lower() in low:
                add_tooltip(w, tip)
                count += 1
                break
    return count

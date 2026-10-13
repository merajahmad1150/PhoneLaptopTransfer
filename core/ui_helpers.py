"""
core/ui_helpers.py
Keyboard + mouse behaviour shared by every window:

  * RIGHT-CLICK on a text box PASTES at once (at the clicked position; it only
    replaces text if you had selected some). If the box is read-only or the
    clipboard is empty, a Cut/Copy/Paste/Select-All menu appears instead.
    Shift+Right-click (or the keyboard Menu key) always shows the full menu.
    (Setting "right-click pastes" can be switched off in Settings.)
  * Ctrl+A selects all (Tk's default on Windows moves the cursor instead).
  * Ctrl+C / Ctrl+X / Ctrl+V work everywhere (Tk built-ins, plus read-only logs).
  * Enter moves to the next field.
  * Mouse wheel scrolls whatever panel the pointer is over.
"""

import tkinter as tk
from tkinter import ttk

from logger import get_logger

log = get_logger()

_settings = {"right_click_pastes": True}
_scroll_canvases = []
_wheel_installed = {"done": False}


def set_right_click_pastes(value: bool) -> None:
    _settings["right_click_pastes"] = bool(value)


# ---------------------------------------------------------------------- #
# small widget helpers
# ---------------------------------------------------------------------- #
def _is_text(widget) -> bool:
    return isinstance(widget, tk.Text)


def _is_editable(widget) -> bool:
    try:
        if hasattr(widget, "instate"):                       # ttk widgets
            return bool(widget.instate(["!disabled", "!readonly"]))
        return str(widget.cget("state")) == "normal"
    except tk.TclError:
        return False


def _has_selection(widget) -> bool:
    try:
        if _is_text(widget):
            return bool(widget.tag_ranges("sel"))
        return bool(widget.selection_present())
    except tk.TclError:
        return False


def _clipboard_text(widget) -> str:
    try:
        return widget.clipboard_get()
    except tk.TclError:
        return ""


def _paste(widget, text: str) -> None:
    """Insert `text` at the cursor; replace the selection only if there is one."""
    if _is_text(widget):
        if widget.tag_ranges("sel"):
            widget.delete("sel.first", "sel.last")
        widget.insert("insert", text)
        widget.see("insert")
    else:
        text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        if widget.selection_present():
            widget.delete("sel.first", "sel.last")
        widget.insert("insert", text)


def _select_all(widget) -> None:
    try:
        if _is_text(widget):
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
        else:
            widget.select_range(0, "end")
            widget.icursor("end")
    except tk.TclError:
        pass


def _place_cursor_at_click(widget, event) -> None:
    try:
        if _is_text(widget):
            widget.mark_set("insert", f"@{event.x},{event.y}")
        else:
            widget.icursor(widget.index(f"@{event.x}"))
    except tk.TclError:
        pass


# ---------------------------------------------------------------------- #
# context menu / right click
# ---------------------------------------------------------------------- #
def _show_menu(event, widget, menu: tk.Menu) -> None:
    editable = _is_editable(widget)
    has_sel = _has_selection(widget)
    has_clip = bool(_clipboard_text(widget))
    menu.entryconfigure("Cut", state="normal" if (editable and has_sel) else "disabled")
    menu.entryconfigure("Copy", state="normal" if has_sel else "disabled")
    menu.entryconfigure("Paste", state="normal" if (editable and has_clip) else "disabled")
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def add_context_menu(widget) -> tk.Menu:
    """Attach right-click behaviour + Ctrl+A to an Entry/Combobox/Text widget."""
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="Cut", accelerator="Ctrl+X", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="Paste", accelerator="Ctrl+V", command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Select All", accelerator="Ctrl+A", command=lambda: _select_all(widget))

    def on_right_click(event):
        widget.focus_set()
        shift = bool(event.state & 0x0001)
        if _settings["right_click_pastes"] and not shift and _is_editable(widget):
            text = _clipboard_text(widget)
            if text:
                if not _has_selection(widget):
                    _place_cursor_at_click(widget, event)
                try:
                    _paste(widget, text)
                except tk.TclError:
                    log.debug("Right-click paste failed", exc_info=True)
                return "break"
        _show_menu(event, widget, menu)
        return "break"

    def on_menu_key(event):
        _show_menu(event, widget, menu)
        return "break"

    def on_ctrl_a(_event):
        _select_all(widget)
        return "break"

    widget.bind("<Button-3>", on_right_click)
    widget.bind("<Shift-Button-3>", on_menu_key)
    widget.bind("<App>", lambda e: on_menu_key(type("E", (), {"x_root": widget.winfo_rootx() + 10,
                                                              "y_root": widget.winfo_rooty() + 20})()))
    widget.bind("<Control-a>", on_ctrl_a)
    widget.bind("<Control-A>", on_ctrl_a)
    if not _is_text(widget):
        return menu
    # Text widgets: clicking a read-only/disabled Text should still allow Ctrl+C
    widget.bind("<Button-1>", lambda e: widget.focus_set(), add="+")
    return menu


def bind_enter_to_next(widget) -> None:
    """Enter moves focus to the next field (like Tab)."""
    def handler(event):
        try:
            nxt = event.widget.tk_focusNext()
            if nxt:
                nxt.focus_set()
        except tk.TclError:
            pass
        return "break"
    widget.bind("<Return>", handler)
    widget.bind("<KP_Enter>", handler)


def wire_field(widget, enter_to_next: bool = True) -> None:
    add_context_menu(widget)
    if enter_to_next and not _is_text(widget):
        bind_enter_to_next(widget)


# ---------------------------------------------------------------------- #
# scrolling
# ---------------------------------------------------------------------- #
def _install_global_wheel(root) -> None:
    if _wheel_installed["done"]:
        return
    _wheel_installed["done"] = True

    def on_wheel(event):
        w = event.widget
        while w is not None and not isinstance(w, str):
            if isinstance(w, (tk.Text, tk.Listbox, ttk.Treeview)):
                return None                       # these scroll themselves
            if w in _scroll_canvases:
                top, bottom = w.yview()
                if top == 0.0 and bottom == 1.0:
                    return None
                w.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return "break"
            w = getattr(w, "master", None)
        return None

    root.bind_all("<MouseWheel>", on_wheel)


def make_scrollable(parent) -> ttk.Frame:
    """Returns an inner frame inside a vertically scrollable canvas."""
    canvas = tk.Canvas(parent, highlightthickness=0, bd=0, bg="#0f0d24")
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas)
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    _scroll_canvases.append(canvas)
    _install_global_wheel(parent.winfo_toplevel())
    return inner


# ---------------------------------------------------------------------- #
# global keyboard shortcuts
# ---------------------------------------------------------------------- #
def bind_shortcuts(root, mapping: dict) -> None:
    """mapping: {'<Control-s>': callable, ...}. Errors are logged, never raised."""
    for sequence, fn in mapping.items():
        def make(f, seq):
            def handler(event):
                try:
                    f()
                except Exception:
                    log.error("Shortcut %s failed", seq, exc_info=True)
                return "break"
            return handler
        root.bind_all(sequence, make(fn, sequence))

"""
core/ui_helpers.py
Tkinter doesn't give Entry/Combobox/Text widgets a right-click menu or an
Enter-to-next-field behavior out of the box. This module adds both, so
every text field in the app behaves like a normal desktop app field:
right-click to Cut/Copy/Paste/Select All, and Enter moves to the next
field. Native paste already inserts at the cursor and replaces only an
active selection (Tkinter's default), which matches what's wanted here.

Also provides make_scrollable(), since a tab's content can end up taller
than the window (e.g. the Public Access tab's QR code was getting cut off
at the bottom with no way to reach it) - every tab is built inside one of
these instead of directly on the raw notebook frame.
"""

import tkinter as tk
from tkinter import ttk

import theme


def add_context_menu(widget) -> tk.Menu:
    """Attach a right-click Cut/Copy/Paste/Select All menu to a widget
    (Entry, ttk.Combobox, or Text). Actions that don't apply to a
    read-only widget just silently no-op instead of raising."""
    menu = tk.Menu(widget, tearoff=0)

    def _fire(virtual_event):
        try:
            widget.event_generate(virtual_event)
        except tk.TclError:
            pass  # e.g. Cut/Paste on a read-only field - nothing to do

    def _select_all():
        try:
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end")
            else:
                widget.selection_range(0, "end")
        except tk.TclError:
            pass

    menu.add_command(label="Cut", command=lambda: _fire("<<Cut>>"))
    menu.add_command(label="Copy", command=lambda: _fire("<<Copy>>"))
    menu.add_command(label="Paste", command=lambda: _fire("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Select All", command=_select_all)

    def _show(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    widget.bind("<Button-3>", _show)  # right-click on Windows
    return menu


def bind_enter_to_next(widget) -> None:
    """Pressing Enter in this widget moves keyboard focus to the next
    widget in tab order instead of doing nothing (Entry) or inserting a
    newline (Text)."""

    def _handler(event):
        nxt = widget.tk_focus_next()
        if nxt is not None:
            nxt.focus_set()
        return "break"  # stop default behavior (e.g. newline in a Text box)

    widget.bind("<Return>", _handler)


def wire_field(widget, enter_to_next: bool = True) -> None:
    """Convenience: apply both the context menu and Enter-to-next binding
    to a single field in one call."""
    add_context_menu(widget)
    if enter_to_next:
        bind_enter_to_next(widget)


def make_scrollable(parent: tk.Widget) -> ttk.Frame:
    """
    Wrap a notebook tab's content in a vertically-scrollable area, so a
    tab whose content is taller than the window (e.g. lots of stacked
    sections, a QR code near the bottom) never gets silently clipped with
    no way to reach the rest of it.

    Returns an inner ttk.Frame - build the tab's contents into THAT frame
    (pack/grid onto it) instead of directly onto `parent`.
    """
    canvas = tk.Canvas(parent, highlightthickness=0, bg=theme.BG)
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas)

    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    # Keep the inner frame's width matched to the canvas so widgets that
    # fill="x" actually span the visible width instead of the scrollregion's.
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Only capture the mouse wheel while the pointer is actually over this
    # tab's canvas, so scrolling one tab doesn't affect any other.
    def _on_enter(_event):
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    def _on_leave(_event):
        canvas.unbind_all("<MouseWheel>")

    canvas.bind("<Enter>", _on_enter)
    canvas.bind("<Leave>", _on_leave)

    return inner

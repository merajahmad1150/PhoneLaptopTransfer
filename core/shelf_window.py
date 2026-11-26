"""
core/shelf_window.py
The Clip Shelf: a small always-on-top window that holds the texts (captions, hashtags, comment replies...) and files
(documents, pictures, videos, mp3, PDFs...) you use again and again.

  * Always on top, movable (drag the top strip), resizable (corner grip), see-through (opacity), hide button (collapses to
    a thin tab on the screen edge) and a global hotkey that shows/hides it from anywhere.
  * Clicking it does NOT steal keyboard focus, so a double-click copies the item AND presses Ctrl+V in the app you were using.
  * Drag items OUT of the shelf into any app (text -> text boxes, files -> Explorer/WhatsApp/Instagram web ...);
    drag text/files IN from anywhere.  Paste a Win+Shift+S screenshot with the hotkey or the + button.
  * Edit, rename, delete, move to top / middle / bottom / up / down (right-click or Alt+Up / Alt+Down).
  * Tiny: no logo, no clutter, thumbnails are never loaded; only short records are kept in memory.
"""

import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import clipboard_helper
import dnd
import tooltip
import ui_helpers
import win_helpers
from config import data_dir, shelf_dir
from logger import get_logger
from shelf_store import ShelfStore

log = get_logger()

BG, HDR, BORDER = "#14112e", "#241e55", "#3b3480"
TEXT, MUTED, SEL = "#f1efff", "#a39fd0", "#4a3fb5"
TAB_W, TAB_H = 24, 110        # the collapsed tab is big enough to drop things onto


class ClipShelf:
    def __init__(self, root, cfg: dict, save_cfg, send_text=None, send_file=None, standalone: bool = False):
        self.root, self.cfg, self.save_cfg = root, cfg, save_cfg
        self.send_text, self.send_file, self.standalone = send_text, send_file, standalone
        self.store = ShelfStore(data_dir() / "shelf.json", shelf_dir())
        self._rows = []              # item ids shown, top to bottom
        self._collapsed = False
        self._saved_geo = None
        self._drag = None
        self._flash_after = None
        self._search_visible = False
        self.hotkeys = win_helpers.Hotkeys()
        self._build()
        self._start_hotkeys()
        self.refresh()
        root.after(150, self._poll)
        root.after(4000, self._stay_on_top)
        if cfg.get("shelf_collapsed"):
            root.after(300, self.collapse)
        log.info("Clip Shelf ready (%d item(s)); drag-and-drop %s", len(self.store.items),
                 "enabled" if dnd.is_ready(self.win) else "unavailable")

    # ------------------------------------------------------------------ #
    # window
    # ------------------------------------------------------------------ #
    def _build(self):
        c = self.cfg
        w = self.win = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.configure(bg=BORDER)
        w.attributes("-topmost", bool(c.get("shelf_topmost", True)))
        w.attributes("-alpha", float(c.get("shelf_opacity", 0.96)))
        self.body = tk.Frame(w, bg=BG)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)

        # ---- top strip: [+] [=]  .......drag.......  [-] [x]
        self.hdr = tk.Frame(self.body, bg=HDR, height=22)
        self.hdr.pack(fill="x")
        self.hdr.pack_propagate(False)
        self._hbtn(self.hdr, "+", self._add_menu, "Add: paste what is on the clipboard (text, picture or files), choose files, or write a new text.", "left")
        self._hbtn(self.hdr, "\u2261", self._main_menu, "Shelf settings: always on top, focus behaviour, opacity, text size, search, hotkeys.", "left")
        self._hbtn(self.hdr, "\u00d7", self._close, "Close the shelf" + (" (exits)" if self.standalone else " (bring it back with the hotkey or the button in the main window)"), "right")
        self._hbtn(self.hdr, "\u2013", self.collapse, "Hide: shrink to a thin tab on the screen edge. Click the tab (or press the hotkey) to bring it back.", "right")
        for wdg in (self.hdr,):
            wdg.bind("<ButtonPress-1>", self._move_start)
            wdg.bind("<B1-Motion>", self._move_do)
            wdg.bind("<ButtonRelease-1>", self._move_end)
            wdg.bind("<Double-Button-1>", lambda e: self.collapse())

        # ---- search (hidden until used)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self.body, textvariable=self.search_var, bg="#0f0d24", fg=TEXT, insertbackground=TEXT,
                                     relief="flat", font=("Segoe UI", 9), highlightthickness=1, highlightbackground=BORDER)
        self.search_var.trace_add("write", lambda *a: self.refresh())
        self.search_entry.bind("<Escape>", lambda e: self.toggle_search(False))
        ui_helpers.wire_field(self.search_entry, enter_to_next=False)

        # ---- list
        mid = tk.Frame(self.body, bg=BG)
        mid.pack(fill="both", expand=True)
        self.lb = tk.Listbox(mid, bg=BG, fg=TEXT, selectbackground=SEL, selectforeground="#ffffff", bd=0, highlightthickness=0,
                             activestyle="none", exportselection=False, font=("Segoe UI", int(c.get("shelf_font_size", 10))))
        sb = tk.Scrollbar(mid, orient="vertical", command=self.lb.yview, width=8, bd=0, troughcolor=BG, bg=HDR)
        self.lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.lb.pack(side="left", fill="both", expand=True)
        self.lb.bind("<Double-Button-1>", lambda e: self.use_selected())
        self.lb.bind("<Return>", lambda e: self.use_selected())
        self.lb.bind("<Delete>", lambda e: self.delete_selected())
        self.lb.bind("<F2>", lambda e: self.edit_selected())
        self.lb.bind("<Alt-Up>", lambda e: self.move_selected("up"))
        self.lb.bind("<Alt-Down>", lambda e: self.move_selected("down"))
        self.lb.bind("<Control-v>", lambda e: self.capture_clipboard())
        self.lb.bind("/", lambda e: self.toggle_search(True))
        self.lb.bind("<Button-3>", self._context_menu)
        self.lb.bind("<Button-1>", self._select_under_pointer, add="+")

        # ---- bottom: tiny status + resize grip
        bot = tk.Frame(self.body, bg=BG, height=14)
        bot.pack(fill="x")
        bot.pack_propagate(False)
        self.status = tk.Label(bot, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=4)
        grip = tk.Label(bot, text="\u25e2", bg=BG, fg=MUTED, cursor="size_nw_se", font=("Segoe UI", 8))
        grip.pack(side="right")
        grip.bind("<ButtonPress-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize_do)
        grip.bind("<ButtonRelease-1>", self._move_end)
        tooltip.add_tooltip(grip, "Drag to resize the shelf.")

        # ---- collapsed tab
        self._tab_char = "\u2039"
        self.tab = tk.Label(w, text=self._tab_char, bg=HDR, fg=TEXT, cursor="hand2", font=("Segoe UI", 12, "bold"))
        self.tab.bind("<Button-1>", lambda e: self.expand())
        tooltip.add_tooltip(self.tab, "Clip Shelf - click to open. You can also DROP text or files onto this tab to save them.")

        # ---- drag and drop
        for target in (self.lb, self.hdr, self.body):
            dnd.drop_target(target, files_cb=self.add_paths, text_cb=self.add_text)
        # the collapsed tab accepts drops too, so anything can be dragged in without opening the shelf
        dnd.drop_target(self.tab, files_cb=self._tab_drop_files, text_cb=self._tab_drop_text, hover_cb=self._tab_hover)
        dnd.drag_source(self.lb, self._drag_payload)
        if not dnd.is_ready(self.win):                    # no drop engine: allow reordering by dragging inside the list
            self.lb.bind("<B1-Motion>", self._reorder_motion)

        self._place_initial()
        w.deiconify()
        if c.get("shelf_noactivate", True):
            win_helpers.set_noactivate(w, True)

    # ---- collapsed tab as a drop target ----
    def _tab_hover(self, on: bool):
        if self._collapsed:
            self.tab.configure(text="+" if on else self._tab_char, bg="#22d3b8" if on else HDR, fg="#06231f" if on else TEXT)

    def _tab_done(self, ok: bool):
        if not self._collapsed:
            return
        self.tab.configure(text="\u2713" if ok else "!", bg="#34d67a" if ok else "#ff6b6b", fg="#06231f")
        self.win.after(900, lambda: self.tab.configure(text=self._tab_char, bg=HDR, fg=TEXT))

    def _tab_drop_files(self, paths):
        before = len(self.store.items)
        self.add_paths(paths)
        self._tab_done(len(self.store.items) > before)

    def _tab_drop_text(self, text):
        self._tab_done(bool(self.add_text(text)))

    def _hbtn(self, parent, text, command, tip, side):
        b = tk.Label(parent, text=text, bg=HDR, fg=TEXT, width=2, cursor="hand2", font=("Segoe UI", 10, "bold"))
        b.pack(side=side, fill="y")
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(bg=SEL), add="+")
        b.bind("<Leave>", lambda e: b.configure(bg=HDR), add="+")
        tooltip.add_tooltip(b, tip)
        return b

    # ------------------------------------------------------------------ #
    # position / size
    # ------------------------------------------------------------------ #
    def _screen(self):
        return self.win.winfo_screenwidth(), self.win.winfo_screenheight()

    def _clamp(self, x, y, w, h):
        sw, sh = self._screen()
        return max(0, min(x, sw - 40)), max(0, min(y, sh - 40)), max(w, 160), max(h, 120)

    def _place_initial(self):
        c = self.cfg
        sw, sh = self._screen()
        w, h = int(c.get("shelf_w", 300)), int(c.get("shelf_h", 380))
        x = int(c.get("shelf_x", -1))
        y = int(c.get("shelf_y", -1))
        if x < 0 or y < 0:
            x, y = sw - w - 18, max(80, (sh - h) // 3)
        x, y, w, h = self._clamp(x, y, w, h)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self._saved_geo = (x, y, w, h)

    def _remember_geometry(self):
        if self._collapsed:
            return
        w = self.win
        self._saved_geo = (w.winfo_x(), w.winfo_y(), w.winfo_width(), w.winfo_height())
        self.cfg.update(shelf_x=self._saved_geo[0], shelf_y=self._saved_geo[1], shelf_w=self._saved_geo[2], shelf_h=self._saved_geo[3])
        self.save_cfg(self.cfg)

    def _move_start(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _move_do(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _move_end(self, e):
        self._drag = None
        self._remember_geometry()

    def _resize_start(self, e):
        self._drag = (e.x_root, e.y_root, self.win.winfo_width(), self.win.winfo_height())

    def _resize_do(self, e):
        if self._drag and len(self._drag) == 4:
            w = max(160, self._drag[2] + e.x_root - self._drag[0])
            h = max(120, self._drag[3] + e.y_root - self._drag[1])
            self.win.geometry(f"{w}x{h}")

    def _stay_on_top(self):
        """Some windows grab 'top' for themselves; re-assert it now and then (cheap)."""
        try:
            if self.cfg.get("shelf_topmost", True) and self.win.winfo_viewable():
                self.win.attributes("-topmost", True)
            self.root.after(4000, self._stay_on_top)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    # show / hide
    # ------------------------------------------------------------------ #
    def collapse(self):
        if self._collapsed:
            return
        self._remember_geometry()
        x, y, w, h = self._saved_geo
        sw, _ = self._screen()
        right = x + w / 2 > sw / 2
        self.body.pack_forget()
        self._tab_char = "\u2039" if right else "\u203a"
        self.tab.configure(text=self._tab_char, bg=HDR)
        self.tab.pack(fill="both", expand=True)
        self.win.geometry(f"{TAB_W}x{TAB_H}+{sw - TAB_W if right else 0}+{y}")
        self._collapsed = True
        self.cfg["shelf_collapsed"] = True
        self.save_cfg(self.cfg)

    def expand(self):
        if not self._collapsed:
            return
        self.tab.pack_forget()
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        x, y, w, h = self._clamp(*self._saved_geo)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self._collapsed = False
        self.cfg["shelf_collapsed"] = False
        self.save_cfg(self.cfg)

    def show(self):
        self.win.deiconify()
        self.win.attributes("-topmost", bool(self.cfg.get("shelf_topmost", True)))
        self.expand()
        self.win.lift()

    def hide(self):
        self.win.withdraw()

    def toggle(self):
        """Hotkey: hidden -> shown; shown -> collapsed to the edge tab."""
        if not self.win.winfo_viewable():
            self.show()
        elif self._collapsed:
            self.expand()
        else:
            self.collapse()

    def _close(self):
        if self.standalone:
            self.destroy()
            self.root.destroy()
        else:
            self.hide()

    def destroy(self):
        try:
            self.hotkeys.stop()
            self.store.save(now=True)
            self.win.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    # list
    # ------------------------------------------------------------------ #
    def refresh(self, keep_id: int = None):
        sel_id = keep_id if keep_id is not None else self._selected_id()
        items = self.store.view(self.search_var.get())
        self._rows = [i["id"] for i in items]
        self.lb.delete(0, "end")
        for n, it in enumerate(items):
            self.lb.insert("end", " " + ShelfStore.display(it))
            self.lb.itemconfig(n, fg=ShelfStore.color(it))
        if sel_id in self._rows:
            idx = self._rows.index(sel_id)
            self.lb.selection_set(idx)
            self.lb.see(idx)

    def _selected_id(self):
        sel = self.lb.curselection()
        return self._rows[sel[0]] if sel and sel[0] < len(self._rows) else None

    def _select_under_pointer(self, e):
        idx = self.lb.nearest(e.y)
        if 0 <= idx < len(self._rows):
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(idx)

    def _flash(self, text: str, ms: int = 1400):
        self.status.configure(text=text)
        if self._flash_after:
            try:
                self.win.after_cancel(self._flash_after)
            except tk.TclError:
                pass
        self._flash_after = self.win.after(ms, lambda: self.status.configure(text=""))

    # ------------------------------------------------------------------ #
    # adding
    # ------------------------------------------------------------------ #
    def add_text(self, text: str):
        text = (text or "").rstrip()
        if not text.strip():
            return None
        same = next((i for i in self.store.items if i["kind"] == "text" and i["text"].strip() == text.strip()), None)
        if same:                                   # the log showed the same caption saved again and again
            self.store.move(same["id"], "top")
            self.refresh(same["id"])
            self._flash("Already saved - moved to top")
            return same
        item = self.store.add_text(text)
        if item:
            self.refresh(item["id"])
            self._flash("Saved")
        return item

    def add_paths(self, paths):
        n = 0
        for p in paths:
            if self.store.add_file(p, copy=bool(self.cfg.get("shelf_copy_files", False))):
                n += 1
        if n:
            self.refresh(self.store.items[0]["id"])
            self._flash(f"{n} added")

    def capture_clipboard(self):
        """Save whatever is on the clipboard: a picture (screenshot), copied files, or text."""
        kind, payload = clipboard_helper.grab_image_or_files()
        if kind == "image":
            item = self.store.add_image(payload)
            self.refresh(item["id"])
            self._flash("Picture saved")
            return
        if kind == "files":
            self.add_paths(payload)
            return
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if text.strip():
            self.add_text(text)
        else:
            self._flash("Clipboard is empty")

    def _add_files_dialog(self):
        self._focusable(True)
        files = filedialog.askopenfilenames(title="Add files to the shelf")
        self._focusable(False)
        if files:
            self.add_paths(files)

    def _new_text_dialog(self):
        text = self._ask_text("New text", "", multiline=True)
        if text:
            self.add_text(text)

    # ------------------------------------------------------------------ #
    # using items
    # ------------------------------------------------------------------ #
    def use_selected(self):
        iid = self._selected_id()
        if iid is None:
            return
        it = self.store.get(iid)
        if not it:
            return
        ok = False
        if it["kind"] == "text":
            ok = clipboard_helper.copy_text(it["text"])
        else:
            p = it.get("path", "")
            if not os.path.exists(p):
                self._flash("File not found")
                log.warning("Shelf: '%s' no longer exists at %s", it.get("label"), p)
                return
            ok = self._copy_file_item(p)
        if not ok:
            self._flash("Could not copy")
            return
        if self.cfg.get("shelf_dblclick", "paste") == "paste":
            self.win.after(150, win_helpers.send_ctrl_v)
            self._flash("Pasted")
        else:
            self._flash("Copied")

    def _copy_file_item(self, path: str) -> bool:
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
            try:
                from PIL import Image
                with Image.open(path) as im:
                    im.load()
                    return clipboard_helper.copy_image(im)
            except Exception:
                log.debug("Shelf: could not load '%s' as a picture, copying it as a file", path, exc_info=True)
        return clipboard_helper.copy_files([path])

    def copy_selected(self, as_file: bool = False):
        iid = self._selected_id()
        it = self.store.get(iid) if iid is not None else None
        if not it:
            return
        if it["kind"] == "text":
            ok = clipboard_helper.copy_text(it["text"])
        else:
            ok = clipboard_helper.copy_files([it["path"]]) if as_file or not self._is_image(it["path"]) else self._copy_file_item(it["path"])
        self._flash("Copied" if ok else "Could not copy")

    @staticmethod
    def _is_image(p):
        return p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"))

    # ------------------------------------------------------------------ #
    # editing
    # ------------------------------------------------------------------ #
    def edit_selected(self):
        iid = self._selected_id()
        it = self.store.get(iid) if iid is not None else None
        if not it:
            return
        if it["kind"] == "text":
            new = self._ask_text("Edit text", it["text"], multiline=True)
            if new is not None and self.store.update_text(iid, new):
                self.refresh(iid)
        else:
            new = self._ask_text("Rename (only the name shown in the shelf)", it.get("label", ""), multiline=False)
            if new is not None and self.store.rename(iid, new):
                self.refresh(iid)

    def replace_selected_file(self):
        iid = self._selected_id()
        it = self.store.get(iid) if iid is not None else None
        if not it or it["kind"] != "file":
            return
        self._focusable(True)
        p = filedialog.askopenfilename(title="Choose the new file")
        self._focusable(False)
        if p and self.store.replace_file(iid, p):
            self.refresh(iid)

    def delete_selected(self):
        iid = self._selected_id()
        if iid is None:
            return
        pos = self._rows.index(iid)
        self.store.delete(iid)
        self.refresh()
        if self._rows:
            self.lb.selection_set(min(pos, len(self._rows) - 1))

    def move_selected(self, where: str):
        iid = self._selected_id()
        if iid is not None and self.store.move(iid, where):
            self.refresh(iid)

    def _reorder_motion(self, e):
        """Fallback (no drop engine): drag an item up/down inside the list to reorder."""
        iid = self._selected_id()
        if iid is None or self.search_var.get():
            return
        idx = max(0, min(self.lb.nearest(e.y), len(self._rows) - 1))
        if self._rows[idx] != iid:
            self.store.move_to_index(iid, idx)
            self.refresh(iid)

    def send_selected_to_phone(self):
        iid = self._selected_id()
        it = self.store.get(iid) if iid is not None else None
        if not it:
            return
        if it["kind"] == "text" and self.send_text:
            self.send_text(it["text"])
            self._flash("Sent to phone")
        elif it["kind"] == "file" and self.send_file and os.path.exists(it["path"]):
            self.send_file(it["path"])
            self._flash("Sending to phone")

    def reveal_selected(self):
        iid = self._selected_id()
        it = self.store.get(iid) if iid is not None else None
        if it and it["kind"] == "file" and os.path.exists(it["path"]):
            subprocess.Popen(["explorer", f"/select,{it['path']}"])

    # ------------------------------------------------------------------ #
    # drag OUT
    # ------------------------------------------------------------------ #
    def _drag_payload(self, event):
        # tkinterdnd2's event has NO .y (the log showed AttributeError and every drag-out failed); use screen coordinates.
        y_root = getattr(event, "y_root", None)
        y = (y_root - self.lb.winfo_rooty()) if y_root is not None else (self.lb.winfo_pointery() - self.lb.winfo_rooty())
        idx = self.lb.nearest(y)
        if not (0 <= idx < len(self._rows)):
            return None
        it = self.store.get(self._rows[idx])
        if not it:
            return None
        if it["kind"] == "text":
            return ("text", it["text"])
        return ("files", [it["path"]]) if os.path.exists(it["path"]) else None

    # ------------------------------------------------------------------ #
    # menus
    # ------------------------------------------------------------------ #
    def _popup(self, menu, x, y):
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _add_menu(self):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label="Paste from clipboard (text / picture / files)", command=self.capture_clipboard)
        m.add_command(label="Add files...", command=self._add_files_dialog)
        m.add_command(label="New text...", command=self._new_text_dialog)
        self._popup(m, self.win.winfo_pointerx(), self.win.winfo_pointery())

    def _context_menu(self, e):
        self._select_under_pointer(e)
        iid = self._selected_id()
        it = self.store.get(iid) if iid is not None else None
        m = tk.Menu(self.win, tearoff=0)
        if it:
            m.add_command(label="Use (paste into the active app)", command=self.use_selected)
            m.add_command(label="Copy", command=lambda: self.copy_selected())
            if it["kind"] == "file":
                m.add_command(label="Copy as file", command=lambda: self.copy_selected(as_file=True))
            m.add_command(label="Edit..." if it["kind"] == "text" else "Rename...", command=self.edit_selected)
            if it["kind"] == "file":
                m.add_command(label="Replace file...", command=self.replace_selected_file)
                m.add_command(label="Show in Explorer", command=self.reveal_selected)
            if (it["kind"] == "text" and self.send_text) or (it["kind"] == "file" and self.send_file):
                m.add_command(label="Send to phone", command=self.send_selected_to_phone)
            m.add_separator()
            for label, where in (("Move to top", "top"), ("Move to middle", "middle"), ("Move to bottom", "bottom"),
                                 ("Move up   (Alt+Up)", "up"), ("Move down   (Alt+Down)", "down")):
                m.add_command(label=label, command=lambda w=where: self.move_selected(w))
            m.add_separator()
            m.add_command(label="Delete   (Del)", command=self.delete_selected)
            m.add_separator()
        m.add_command(label="Paste clipboard into the shelf", command=self.capture_clipboard)
        self._popup(m, e.x_root, e.y_root)

    def _main_menu(self):
        c = self.cfg
        m = tk.Menu(self.win, tearoff=0)
        self._v_top = tk.BooleanVar(value=bool(c.get("shelf_topmost", True)))
        self._v_noact = tk.BooleanVar(value=bool(c.get("shelf_noactivate", True)))
        self._v_copy = tk.BooleanVar(value=bool(c.get("shelf_copy_files", False)))
        self._v_dbl = tk.StringVar(value=c.get("shelf_dblclick", "paste"))
        m.add_checkbutton(label="Always on top", variable=self._v_top, command=lambda: self._set("shelf_topmost", self._v_top.get()))
        m.add_checkbutton(label="Don't take focus when clicked", variable=self._v_noact,
                          command=lambda: self._set("shelf_noactivate", self._v_noact.get()))
        m.add_radiobutton(label="Double-click: copy + paste into the active app", variable=self._v_dbl, value="paste",
                          command=lambda: self._set("shelf_dblclick", "paste"))
        m.add_radiobutton(label="Double-click: copy only", variable=self._v_dbl, value="copy",
                          command=lambda: self._set("shelf_dblclick", "copy"))
        m.add_checkbutton(label="Keep a private copy of dropped files", variable=self._v_copy,
                          command=lambda: self._set("shelf_copy_files", self._v_copy.get()))
        op = tk.Menu(m, tearoff=0)
        for pct in (100, 90, 80, 60, 40):
            op.add_command(label=f"{pct}%", command=lambda p=pct: self._set("shelf_opacity", p / 100))
        m.add_cascade(label="Opacity", menu=op)
        fs = tk.Menu(m, tearoff=0)
        for size in (9, 10, 11, 13, 15):
            fs.add_command(label=f"{size} pt", command=lambda s=size: self._set("shelf_font_size", s))
        m.add_cascade(label="Text size", menu=fs)
        m.add_separator()
        m.add_command(label="Search  (/)", command=lambda: self.toggle_search(True))
        m.add_command(label="Open the shelf data folder", command=lambda: os.startfile(str(shelf_dir())) if os.name == "nt" else None)
        m.add_command(label="Reset size and position", command=self._reset_geometry)
        m.add_command(label="Hotkeys...", command=lambda: messagebox.showinfo(
            "Clip Shelf hotkeys",
            f"{c.get('shelf_hotkey_toggle')}  show / hide the shelf from anywhere\n"
            f"{c.get('shelf_hotkey_add')}  save the clipboard (text, screenshot or files) into the shelf\n\n"
            "In the list: Enter = use, Delete = remove, F2 = edit, Alt+Up / Alt+Down = reorder, / = search.\n"
            "Change the hotkeys in config.json (shelf_hotkey_toggle, shelf_hotkey_add)."))
        self._popup(m, self.win.winfo_pointerx(), self.win.winfo_pointery())

    def _set(self, key, value):
        self.cfg[key] = value
        self.save_cfg(self.cfg)
        if key == "shelf_topmost":
            self.win.attributes("-topmost", bool(value))
        elif key == "shelf_opacity":
            self.win.attributes("-alpha", float(value))
        elif key == "shelf_font_size":
            self.lb.configure(font=("Segoe UI", int(value)))
        elif key == "shelf_noactivate":
            win_helpers.set_noactivate(self.win, bool(value))
        log.info("Shelf setting %s = %s", key, value)

    def _reset_geometry(self):
        self.cfg.update(shelf_x=-1, shelf_y=-1, shelf_w=300, shelf_h=380)
        self._place_initial()
        self._remember_geometry()

    # ------------------------------------------------------------------ #
    # search + keyboard focus
    # ------------------------------------------------------------------ #
    def _focusable(self, yes: bool):
        """Let the shelf take keyboard focus temporarily (search / dialogs), then go back to no-activate."""
        if self.cfg.get("shelf_noactivate", True):
            win_helpers.set_noactivate(self.win, not yes)

    def toggle_search(self, show: bool):
        if show and not self._search_visible:
            self._focusable(True)
            self.search_entry.pack(fill="x", padx=2, pady=2, before=self.lb.master)
            self.search_entry.focus_force()
            self._search_visible = True
        elif not show and self._search_visible:
            self.search_var.set("")
            self.search_entry.pack_forget()
            self._search_visible = False
            self._focusable(False)

    def _ask_text(self, title: str, initial: str, multiline: bool):
        """Small editor window (normal window, can take focus). Returns the new text or None."""
        self._focusable(True)
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.attributes("-topmost", True)
        result = {"v": None}
        if multiline:
            box = tk.Text(dlg, width=60, height=12, wrap="word", bg="#0f0d24", fg=TEXT, insertbackground=TEXT,
                          font=("Segoe UI", 10), relief="flat")
            box.insert("1.0", initial)
            box.pack(fill="both", expand=True, padx=8, pady=8)
            getter = lambda: box.get("1.0", "end-1c")
        else:
            box = tk.Entry(dlg, width=52, bg="#0f0d24", fg=TEXT, insertbackground=TEXT, font=("Segoe UI", 10), relief="flat")
            box.insert(0, initial)
            box.pack(fill="x", padx=8, pady=8)
            getter = lambda: box.get()
        ui_helpers.wire_field(box, enter_to_next=False)
        box.focus_force()

        def done(save):
            result["v"] = getter() if save else None
            dlg.destroy()
        row = tk.Frame(dlg, bg=BG)
        row.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(row, text="Save  (Ctrl+Enter)", command=lambda: done(True), bg="#22d3b8", fg="#06231f", relief="flat", padx=10).pack(side="left")
        tk.Button(row, text="Cancel  (Esc)", command=lambda: done(False), bg=HDR, fg=TEXT, relief="flat", padx=10).pack(side="left", padx=6)
        dlg.bind("<Control-Return>", lambda e: done(True))
        dlg.bind("<Escape>", lambda e: done(False))
        if not multiline:
            box.bind("<Return>", lambda e: done(True))
        dlg.protocol("WM_DELETE_WINDOW", lambda: done(False))
        dlg.grab_set()
        self.root.wait_window(dlg)
        self._focusable(False)
        return result["v"]

    # ------------------------------------------------------------------ #
    # hotkeys
    # ------------------------------------------------------------------ #
    def _start_hotkeys(self):
        bindings = {}
        if self.cfg.get("shelf_hotkey_toggle"):
            bindings[self.cfg["shelf_hotkey_toggle"]] = "toggle"
        if self.cfg.get("shelf_hotkey_add"):
            bindings[self.cfg["shelf_hotkey_add"]] = "add"
        self.hotkeys.start(bindings)

    def _poll(self):
        try:
            action = self.hotkeys.poll()
            while action:
                if action == "toggle":
                    self.toggle()
                elif action == "add":
                    self.capture_clipboard()
                    if self.win.winfo_viewable() and self._collapsed:
                        self.expand()
                action = self.hotkeys.poll()
            self.root.after(150, self._poll)
        except tk.TclError:
            pass

"""
core/main_window.py
The desktop window: gradient header with the logo, a coloured-icon sidebar
(no cramped tabs), the page area, and a live log panel at the bottom.
"""

import queue
import tkinter as tk
import traceback
import zipfile
from datetime import datetime
from tkinter import messagebox, ttk

import icons
import scrcpy_helper
import theme
import ui_helpers
from config import BASE_DIR, logs_dir
from gui_mirror import MirrorMixin
from gui_network import NetworkMixin
from gui_tools import ToolsMixin
from gui_transfer import TransferMixin
from logger import attach_gui_sink, current_log_path, detach_gui_sink, get_logger
from version import APP_NAME, VERSION

log = get_logger()

# (key, label, icon name, shortcut digit)
PAGES = [
    ("transfer", "Wi-Fi Transfer", "transfer"),
    ("text", "Text", "text"),
    ("mirror", "Screen Mirror", "mirror"),
    ("public", "Public Access", "public"),
    ("rooms", "Shared Rooms", "rooms"),
    ("adb", "ADB (USB)", "adb"),
    ("sync", "Auto-Sync", "sync"),
    ("settings", "Settings", "settings"),
]

SHORTCUTS_TEXT = """Keyboard shortcuts

Ctrl+1 ... Ctrl+8     Switch page
F5                    Refresh links / devices / rooms
Ctrl+O                Add files to send to the phone
Ctrl+Shift+O          Add a folder to send to the phone
Ctrl+E                Open the received-files folder
Ctrl+Shift+C          Copy the phone link
Ctrl+Enter            Send the text you typed (Text page)
Ctrl+L                Open the logs folder
F1                    This help
Ctrl+Q                Quit

In any text box
Right-click           Paste right away (replaces only a selection)
Shift+Right-click     Full Cut / Copy / Paste / Select All menu
Ctrl+A / C / X / V    Select all / copy / cut / paste
Enter                 Move to the next field
"""


class MainWindow(TransferMixin, MirrorMixin, NetworkMixin, ToolsMixin):
    def __init__(self, root: tk.Tk, cfg: dict, save_cfg_callback, server):
        self.root = root
        self.cfg = cfg
        self.save_cfg = save_cfg_callback
        self.server = server
        self._uiq = queue.Queue()
        self._logq = queue.Queue()
        self.pages = {}
        self.nav_buttons = {}
        self.current_page = None
        self._closing = False

        root.title(f"{APP_NAME}  v{VERSION}")
        root.geometry("900x860")
        root.minsize(780, 640)
        theme.apply_theme(root)
        icons.set_window_icon(root)
        ui_helpers.set_right_click_pastes(cfg.get("right_click_pastes", True))
        root.report_callback_exception = self._tk_exception

        theme.GradientHeader(root, APP_NAME, "Fast, private file & text transfer between your phone and laptop",
                             logo_image=icons.get_logo(46), height=76).pack(fill="x")

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)
        self.sidebar = ttk.Frame(body, width=190)
        self.sidebar.pack(side="left", fill="y", padx=(6, 0), pady=6)
        self.sidebar.pack_propagate(False)
        self.content = ttk.Frame(body)
        self.content.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        for i, (key, label, icon) in enumerate(PAGES, 1):
            b = ttk.Button(self.sidebar, text=f" {label}", image=icons.get_icon(icon, 22), compound="left",
                           style="Nav.TButton", command=lambda k=key: self.show_page(k))
            b.pack(fill="x", pady=1)
            self.nav_buttons[key] = b
            self.pages[key] = ttk.Frame(self.content)

        ttk.Separator(self.sidebar).pack(fill="x", pady=8)
        ttk.Button(self.sidebar, text=" Shortcuts (F1)", style="Nav.TButton", command=self._show_shortcuts).pack(fill="x")
        ttk.Button(self.sidebar, text=" Quit (Ctrl+Q)", style="Nav.TButton", command=self._on_close).pack(fill="x")

        self._build_log_panel()

        # build every page (a failure in one optional page must not stop the app)
        builders = {"transfer": self._build_transfer_page, "text": self._build_text_page, "mirror": self._build_mirror_page,
                    "public": self._build_public_page, "rooms": self._build_rooms_page, "adb": self._build_adb_page,
                    "sync": self._build_sync_page, "settings": self._build_settings_page}
        for key, fn in builders.items():
            try:
                fn(self.pages[key])
            except Exception:
                log.critical("Could not build the '%s' page:\n%s", key, traceback.format_exc())
                ttk.Label(self.pages[key], text=f"This page failed to load - see the log.\n\n{traceback.format_exc()[-600:]}",
                          wraplength=520, justify="left").pack(padx=20, pady=20)

        self._bind_shortcuts()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_page(cfg.get("last_tab", "transfer") if cfg.get("last_tab") in self.pages else "transfer")
        attach_gui_sink(self._log_sink)
        root.after(50, self._poll_queues)
        log.info("Main window ready (%d pages)", len(self.pages))

        if cfg.get("auto_start_server", True):
            root.after(400, self._auto_start_server)

    # ------------------------------------------------------------------ #
    # threading helpers
    # ------------------------------------------------------------------ #
    def ui(self, fn):
        """Run fn on the UI thread (safe to call from any thread)."""
        self._uiq.put(fn)

    def _log_sink(self, line: str):
        self._logq.put(line)

    def _poll_queues(self):
        if self._closing:
            return
        try:
            for _ in range(100):
                fn = self._uiq.get_nowait()
                try:
                    fn()
                except Exception:
                    log.error("UI task failed:\n%s", traceback.format_exc())
        except queue.Empty:
            pass
        lines = []
        try:
            for _ in range(300):
                lines.append(self._logq.get_nowait())
        except queue.Empty:
            pass
        if lines:
            self._append_log(lines)
        self.root.after(60, self._poll_queues)

    def _safe(self, fn):
        def wrapper(*a, **k):
            try:
                return fn(*a, **k)
            except Exception:
                log.critical("Unhandled error in UI callback:\n%s", traceback.format_exc())
                messagebox.showerror("Something went wrong",
                                     "An error occurred, but the tool stayed open.\n\n"
                                     "Full details are in the log panel and in the session log file.")
        return wrapper

    def _tk_exception(self, exc, val, tb):
        log.critical("Tk callback exception:\n%s", "".join(traceback.format_exception(exc, val, tb)))

    # ------------------------------------------------------------------ #
    # navigation
    # ------------------------------------------------------------------ #
    def show_page(self, key: str):
        if key not in self.pages:
            return
        if self.current_page:
            self.pages[self.current_page].pack_forget()
            self.nav_buttons[self.current_page].configure(style="Nav.TButton")
        self.pages[key].pack(fill="both", expand=True)
        self.nav_buttons[key].configure(style="NavSel.TButton")
        self.current_page = key
        if self.cfg.get("last_tab") != key:
            self.cfg["last_tab"] = key
        if key == "rooms":
            self._refresh_active_rooms()
        elif key == "mirror":
            self._safe(self._refresh_mirror_devices)()

    def _bind_shortcuts(self):
        m = {f"<Control-Key-{i}>": (lambda k=k: self.show_page(k)) for i, (k, _, _) in enumerate(PAGES, 1)}
        m.update({
            "<F5>": self._refresh_all,
            "<Control-o>": self._add_files_to_share,
            "<Control-O>": self._add_folder_to_share,
            "<Control-e>": self._open_received_folder,
            "<Control-C>": lambda: self._copy_text_var(self.lan_url_var),
            "<Control-l>": lambda: self._open_path(logs_dir()),
            "<F1>": self._show_shortcuts,
            "<Control-q>": self._on_close,
        })
        ui_helpers.bind_shortcuts(self.root, m)

    def _refresh_all(self):
        self._refresh_server_ui()
        self.server.public.refresh_now()
        self._refresh_room_links()
        if self.current_page == "mirror":
            self._refresh_mirror_devices()
        elif self.current_page == "rooms":
            self._refresh_active_rooms()

    def _show_shortcuts(self):
        messagebox.showinfo("Keyboard shortcuts", SHORTCUTS_TEXT)

    def _auto_start_server(self):
        if not self.server.is_running:
            self._start_server()
            self._refresh_server_ui()

    # ------------------------------------------------------------------ #
    # log panel
    # ------------------------------------------------------------------ #
    def _build_log_panel(self):
        box = ttk.LabelFrame(self.root, text="Live log  (every detail is also saved in logs\\sessions)")
        box.pack(fill="x", padx=8, pady=(0, 8))
        bar = ttk.Frame(box)
        bar.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Button(bar, text="Open logs folder (Ctrl+L)", command=self._safe(lambda: self._open_path(logs_dir()))).pack(side="left")
        ttk.Button(bar, text="Copy log file path", command=self._safe(self._copy_log_path)).pack(side="left", padx=6)
        ttk.Button(bar, text="Zip recent logs for sharing", command=self._safe(self._zip_logs)).pack(side="left")
        ttk.Button(bar, text="Clear view", command=self._safe(lambda: self._clear_log_view())).pack(side="right")
        inner = ttk.Frame(box)
        inner.pack(fill="x", padx=6, pady=(0, 6))
        self.log_text = tk.Text(inner, height=9, wrap="none", state="disabled")
        theme.style_log_widget(self.log_text)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        ui_helpers.add_context_menu(self.log_text)

    def _append_log(self, lines):
        t = self.log_text
        at_bottom = t.yview()[1] > 0.98
        t.configure(state="normal")
        for line in lines:
            tag = ()
            if "[CRITICAL" in line:
                tag = ("critical",)
            elif "[ERROR" in line:
                tag = ("error",)
            elif "[WARNING" in line:
                tag = ("warning",)
            t.insert("end", line + "\n", tag)
        count = int(t.index("end-1c").split(".")[0])
        if count > 2500:
            t.delete("1.0", f"{count - 2000}.0")
        t.configure(state="disabled")
        if at_bottom:
            t.see("end")

    def _clear_log_view(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _copy_log_path(self):
        p = current_log_path()
        if p:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(p))
            log.info("Log file path copied to the clipboard: %s", p)

    def _zip_logs(self):
        sessions = sorted((logs_dir() / "sessions").glob("session_*.log"))[-10:]
        if not sessions:
            messagebox.showinfo("No logs", "There are no session logs yet.")
            return
        out = logs_dir() / f"logs_to_share_{datetime.now():%Y-%m-%d_%H-%M-%S}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sessions:
                z.write(f, f.name)
        log.info("Zipped the last %d session log(s) -> %s", len(sessions), out)
        self._open_path(logs_dir())
        messagebox.showinfo("Logs zipped", f"Created:\n{out}\n\nSend me this file (it contains the 10 newest sessions).")

    # ------------------------------------------------------------------ #
    def _on_close(self):
        if self._closing:
            return
        self._closing = True
        log.info("Window closing - shutting everything down")
        try:
            detach_gui_sink(self._log_sink)
            if self.server.is_running:
                self.server.stop()
            scrcpy_helper.stop_all()
            self.save_cfg(self.cfg)
        except Exception:
            log.error("Error during shutdown", exc_info=True)
        finally:
            self.root.destroy()

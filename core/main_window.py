"""
core/main_window.py
The desktop window: gradient header with the logo, a coloured-icon sidebar
(no cramped tabs), the page area, and a live log panel at the bottom.
"""

import queue
import signal
import threading
import tkinter as tk
import traceback
import zipfile
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import dnd
import icons
import scrcpy_helper
import theme
import tooltip
import ui_helpers
import win_helpers
from config import BASE_DIR, logs_dir
from gui_mirror import MirrorMixin
from gui_network import NetworkMixin
from gui_selftest import SelfTestMixin
from gui_tools import ToolsMixin
from gui_transfer import TransferMixin
from logger import attach_gui_sink, classify_line, current_log_path, detach_gui_sink, get_logger
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
Ctrl+V                Send a screenshot (Win+Shift+S) or copied files to the phone
Ctrl+Shift+V          Same, from anywhere (also sends clipboard text)
Ctrl+Shift+C          Copy the phone link
Ctrl+Enter            Send the text you typed (Text page)
Ctrl+G                Send files to the phone gallery (Screen Mirror page)
Ctrl+L                Open the logs folder
F1                    This help
Ctrl+Q                Quit

In any text box
Right-click           Paste right away (replaces only a selection)
Shift+Right-click     Full Cut / Copy / Paste / Select All menu
Ctrl+A / C / X / V    Select all / copy / cut / paste
Enter                 Move to the next field

Clip Shelf (the small always-on-top window)
Ctrl+Alt+V            Show / hide the shelf from anywhere (changeable in Settings)
Ctrl+Alt+C            Save whatever is on the clipboard into the shelf
Double-click          Copy the item and paste it into the app you were using
Drag an item out      Drop text or files into any other program
Alt+Up / Alt+Down     Move the selected item up / down;  right-click for top / middle / bottom
"""

# Hover explanations (first matching fragment wins, so specific ones come first)
TIPS = [
    ("Start Server", "Turns the phone-transfer web server on. The phone then opens the page by scanning the QR code."),
    ("Stop Server", "Turns the phone-transfer web server off. Nothing can reach this laptop until you start it again."),
    ("Paste screenshot", "Sends the screenshot you just took (Win+Shift+S) or the files you copied in Explorer to the phone page."),
    ("Run self-test", "Simulates a phone on this laptop: uploads, sends text, downloads and checks the clipboard, then shows speeds and removes the test files."),
    ("Add Files", "Choose files on this laptop to offer to the phone. They appear under 'Get from laptop' on the phone page."),
    ("Add Folder", "Zips a folder (photos/videos are stored, not recompressed) and offers the zip to the phone."),
    ("Open Share Folder", "Opens the folder with the files you are offering to the phone."),
    ("Open Received Folder", "Opens the folder where files from the phone arrive."),
    ("Show in Explorer", "Opens the folder and highlights the selected file."),
    ("Show pairing QR", "Wireless Android pairing: scan this QR from Developer options > Wireless debugging > Pair device with QR code."),
    ("Pair", "Pairs the phone using the address and 6-digit code shown under 'Pair device with pairing code'."),
    ("Connect", "Connects to a phone by ip:port (for example its Tailscale address)."),
    ("Start Mirroring", "Shows the phone screen on this laptop with scrcpy and lets you control it with the mouse."),
    ("Refresh devices", "Looks for Android phones connected with USB or wirelessly."),
    ("Choose photos", "Copies photos/videos into the phone gallery folder (DCIM/PLT) and documents into Download/PLT over ADB, so Instagram, WhatsApp and Gallery can see them."),
    ("Send my Windows clipboard", "Puts the text on your Windows clipboard onto the phone page; tap Copy there. Works for any language."),
    ("Start AirPlay", "Starts the free UxPlay receiver so an iPhone can mirror to this laptop (same Wi-Fi)."),
    ("Save quality", "Saves the mirror quality fields. They also apply automatically when you start mirroring."),
    ("Copy Selected", "Copies the selected text to the Windows clipboard."),
    ("Save As", "Saves the selected text to a file."),
    ("Clear view", "Empties the log panel on screen only (the log file is untouched)."),
    ("Clear", "Removes the items from this list. Saved files and texts stay on the laptop."),
    ("Send to Phone", "Puts the text on the phone page under 'Text from laptop'."),
    ("Run publisher script", "Runs your Tailscale publisher so port 8765 becomes reachable from the internet."),
    ("Check now", "Asks Tailscale right now what is published (it also checks by itself)."),
    ("Copy port", "Copies the port number to publish with Tailscale."),
    ("New PIN", "Makes a new 6-digit access PIN. Visitors of the public link must enter it."),
    ("Ask visitors for a PIN", "Protects the phone page. Strongly recommended while the public link is live."),
    ("Enable Shared Rooms", "Lets other people pair their own devices through a private room on this tool (off by default)."),
    ("Save settings", "Saves everything on this page."),
    ("Keyboard shortcuts", "Shows all keyboard shortcuts."),
    ("Show the live log panel", "Hides or shows the log panel at the bottom."),
    ("Open the Clip Shelf", "The shelf is the small always-on-top window with your saved texts and files."),
    ("Clip Shelf", "Shows or hides the small always-on-top window with your saved captions, replies, hashtags, files and pictures."),
    ("Open logs folder", "Opens the folder with one log file for every run - send me the newest one when something goes wrong."),
    ("Copy log file path", "Copies the path of the current log file."),
    ("Zip recent logs", "Packs the 10 newest session logs into one zip for sharing."),
    ("Push to phone", "Copies the chosen file/folder to the phone over ADB."),
    ("Pull from phone", "Copies a file/folder from the phone to this laptop over ADB."),
    ("Launch Syncthing", "Starts Syncthing for background folder sync."),
    ("Quit", "Closes the tool (the phone page stops working)."),
]
NAV_TIPS = {
    "Wi-Fi Transfer": "Send files and folders between phone and laptop. Shows the QR code to scan.",
    "Text": "Text between phone and laptop, both ways, with the time of every transfer.",
    "Screen Mirror": "See and control your phone on this laptop; send files into the phone gallery.",
    "Public Access": "The internet link (Tailscale) and the access PIN.",
    "Shared Rooms": "Private rooms for other people (optional, off by default).",
    "ADB (USB)": "Direct file transfer with an Android phone over USB or wireless ADB.",
    "Auto-Sync": "Launch Syncthing to keep folders in sync in the background.",
    "Settings": "All settings: paths, behaviour, colours, hide pages, hide the log, the Clip Shelf.",
}



class MainWindow(TransferMixin, MirrorMixin, NetworkMixin, ToolsMixin, SelfTestMixin):
    PAGE_LIST = PAGES

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

        theme.set_gradient(cfg.get("ui_gradient", "Aurora"))
        self.header = theme.GradientHeader(
            root, APP_NAME, "Fast, private file & text transfer between your phone and laptop",
            logo_image=icons.get_logo(46), height=76, gear_image=icons.get_icon("settings", 30),
            on_gear=lambda: self.show_page("settings"), logo_tip=f"{APP_NAME} v{VERSION}\nPhone <-> laptop files, text and screen mirroring.",
            gear_tip="Settings: paths, colours, hide pages or the log, Clip Shelf, behaviour.")
        self.header.pack(fill="x")
        self.dnd_ok = dnd.is_ready(root)

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
            self.nav_buttons[key] = b
            self.pages[key] = ttk.Frame(self.content)
            tooltip.add_tooltip(b, NAV_TIPS.get(label, label))

        self._nav_sep = ttk.Separator(self.sidebar)
        self._nav_sep.pack(fill="x", pady=8)
        ttk.Button(self.sidebar, text=" Clip Shelf", image=icons.get_icon("log", 22), compound="left", style="Nav.TButton",
                   command=self._toggle_shelf).pack(fill="x")
        ttk.Button(self.sidebar, text=" Shortcuts (F1)", style="Nav.TButton", command=self._show_shortcuts).pack(fill="x")
        ttk.Button(self.sidebar, text=" Quit (Ctrl+Q)", style="Nav.TButton", command=self._on_close).pack(fill="x")
        self._layout_nav()

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
        self.shelf = None
        self._register_drops()
        self._apply_log_visibility()
        n = tooltip.attach_tooltips(root, TIPS)
        log.info("Hover explanations attached to %d controls", n)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_page(cfg.get("last_tab", "transfer") if cfg.get("last_tab") in self.pages else "transfer")
        attach_gui_sink(self._log_sink)
        # Ctrl+C in the console used to kill the tool with a crash report (seen twice in the logs).
        # Now it only asks whether you really want to quit.
        self._sigint = False
        try:
            signal.signal(signal.SIGINT, lambda *a: setattr(self, "_sigint", True))
        except (ValueError, OSError):
            log.debug("Could not install the Ctrl+C handler", exc_info=True)
        root.after(50, self._poll_queues)
        log.info("Main window ready (%d pages)", len(self.pages))

        if cfg.get("auto_start_server", True):
            root.after(400, self._auto_start_server)
        if cfg.get("shelf_enabled", True):
            root.after(900, self._start_shelf)

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
        if self._sigint:
            self._sigint = False
            log.warning("Ctrl+C was pressed in the console window")
            if messagebox.askyesno("Quit?", "Ctrl+C was pressed in the console window.\n\nQuit Phone-Laptop Transfer?", default="no"):
                self._on_close()
                return
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
            "<Control-g>": lambda: (self.show_page("mirror"), self._send_files_to_phone_gallery()),
            "<Control-l>": lambda: self._open_path(logs_dir()),
            "<F1>": self._show_shortcuts,
            "<Control-q>": self._on_close,
        })
        ui_helpers.bind_shortcuts(self.root, m)
        # Ctrl+V sends a pasted screenshot/files to the phone, but only when you are NOT typing in a text box
        self.root.bind("<Control-v>", self._on_ctrl_v, add="+")
        self.root.bind("<Control-V>", lambda e: (self._paste_clipboard_to_phone(), "break")[1], add="+")

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
        box = self.log_box = ttk.LabelFrame(self.root, text="Live log  (every detail is also saved in logs\\sessions;  dim = routine, bright = important)")
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
            kind = classify_line(line)       # routine lines dim, important ones highlighted
            tag = ("critical",) if "[CRITICAL" in line else (() if kind == "normal" else (kind,))
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
    # layout / appearance (Settings > Appearance applies these immediately)
    # ------------------------------------------------------------------ #
    def _layout_nav(self):
        hidden = set(self.cfg.get("ui_hidden_pages", []))
        for b in self.nav_buttons.values():
            b.pack_forget()
        for key, _label, _icon in PAGES:
            if key not in hidden or key == "settings":
                self.nav_buttons[key].pack(fill="x", pady=1, before=self._nav_sep)

    def _apply_hidden_pages(self):
        self.cfg["ui_hidden_pages"] = [k for k, v in self.page_vars.items() if not v.get()]
        self.save_cfg(self.cfg)
        self._layout_nav()
        if self.current_page in self.cfg["ui_hidden_pages"]:
            self.show_page("transfer" if "transfer" not in self.cfg["ui_hidden_pages"] else "settings")

    def _apply_log_visibility(self):
        show = bool(self.show_log_var.get()) if hasattr(self, "show_log_var") else bool(self.cfg.get("ui_show_log", True))
        self.cfg["ui_show_log"] = show
        if show:
            self.log_box.pack(fill="x", padx=8, pady=(0, 8))
        else:
            self.log_box.pack_forget()
        self.save_cfg(self.cfg)

    def _apply_gradient(self):
        self.cfg["ui_gradient"] = self.gradient_var.get()
        theme.set_gradient(self.cfg["ui_gradient"])
        self.header.redraw()
        self.save_cfg(self.cfg)

    # ------------------------------------------------------------------ #
    # drag & drop onto the window, Clip Shelf
    # ------------------------------------------------------------------ #
    def _register_drops(self):
        if not self.dnd_ok:
            return
        targets = [self.root, self.content, self.dropzone] + list(self.pages.values())
        ok = sum(1 for t in targets if dnd.drop_target(t, files_cb=self._on_drop_files, text_cb=self._on_drop_text))
        log.info("Drag-and-drop enabled on %d area(s) of the window", ok)

    def _start_shelf(self):
        if self.shelf is not None:
            return
        if not win_helpers.single_instance("PLT_ClipShelf"):
            log.info("The Clip Shelf is already running in another copy of the tool - not opening a second one")
            return
        from shelf_window import ClipShelf
        share = Path(self.cfg["share_folder"])
        self.shelf = ClipShelf(
            self.root, self.cfg, self.save_cfg,
            send_text=lambda t: self.server.text_store.add_to_phone(t),
            send_file=lambda p: threading.Thread(target=self._copy_files_thread, args=([p], share), name="ShelfSend", daemon=True).start())

    def _toggle_shelf(self):
        if self.shelf is None:
            self._start_shelf()
        elif self.shelf is not None:
            if self.shelf.win.winfo_viewable():
                self.shelf.hide()
            else:
                self.shelf.show()

    # ------------------------------------------------------------------ #
    def _on_close(self):
        if self._closing:
            return
        self._closing = True
        log.info("Window closing - shutting everything down")
        try:
            detach_gui_sink(self._log_sink)
            if self.shelf:
                self.shelf.destroy()
            if self.server.is_running:
                self.server.stop()
            scrcpy_helper.stop_all()
            self.save_cfg(self.cfg)
        except Exception:
            log.error("Error during shutdown", exc_info=True)
        finally:
            self.root.destroy()

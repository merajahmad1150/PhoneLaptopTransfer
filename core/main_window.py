"""
core/main_window.py
The Tkinter application window. Tabs:
  - Transfer:      start/stop the Wi-Fi web server, shows URL + QR code, live log
  - Text:          share text of any length, either direction
  - Screen Mirror: mirror + mouse-control the phone via scrcpy (optional)
  - Public Access: publish the server to the internet via Tailscale Funnel (optional)
  - ADB (optional): direct Android push/pull over USB/wireless ADB
  - Auto-Sync (optional): Syncthing launcher/instructions
  - Settings:   folders, port, tool paths

Design goals per the user's stated preferences:
  - Never closes/disappears silently on error; problems are shown in-window.
  - Full-detail, timestamped log always visible in the Transfer tab.
  - Everything editable through the GUI, no config file hand-editing required.
"""

import os
import shutil
import subprocess
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from PIL import ImageTk

import adb_helper, net_utils, qr_helper, room_manager, scrcpy_helper, syncthing_helper, theme
from logger import attach_gui_sink, get_logger
from safe_names import safe_filename
import ui_helpers
from ui_helpers import add_context_menu, wire_field
from web_server import TransferServer

log = get_logger()


class MainWindow:
    def __init__(self, root: tk.Tk, cfg: dict, save_cfg_callback):
        self.root = root
        self.cfg = cfg
        self.save_cfg = save_cfg_callback
        self.server = TransferServer(cfg)
        self._qr_photo = None  # keep a reference so Tkinter doesn't garbage-collect it
        self._public_qr_photo = None
        self._received_files = []  # newest first; index matches self.received_listbox rows

        root.title("Phone \u2194 Laptop Transfer")
        root.geometry("580x720")
        root.minsize(500, 560)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        theme.apply_theme(root)
        theme.make_gradient_header(
            root, "Phone \u2194 Laptop Transfer", "Wi-Fi \u00b7 Text \u00b7 Mirror \u00b7 Public URL, all in one place"
        )

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.transfer_tab = ttk.Frame(notebook)
        self.text_tab = ttk.Frame(notebook)
        self.mirror_tab = ttk.Frame(notebook)
        self.public_tab = ttk.Frame(notebook)
        self.rooms_tab = ttk.Frame(notebook)
        self.adb_tab = ttk.Frame(notebook)
        self.sync_tab = ttk.Frame(notebook)
        self.settings_tab = ttk.Frame(notebook)

        notebook.add(self.transfer_tab, text="Wi-Fi Transfer")
        notebook.add(self.text_tab, text="Text")
        notebook.add(self.mirror_tab, text="Screen Mirror")
        notebook.add(self.public_tab, text="Public Access")
        notebook.add(self.rooms_tab, text="Shared Rooms")
        notebook.add(self.adb_tab, text="ADB (optional)")
        notebook.add(self.sync_tab, text="Auto-Sync (optional)")
        notebook.add(self.settings_tab, text="Settings")

        self._build_transfer_tab()
        self._build_text_tab()
        self._build_mirror_tab()
        self._build_public_tab()
        self._build_rooms_tab()
        self._build_adb_tab()
        self._build_sync_tab()
        self._build_settings_tab()

        self.server.text_store.on_new_to_laptop(self._on_text_received_threadsafe)
        self.server.on_file_received(self._on_file_received_threadsafe)
        attach_gui_sink(self._append_log_threadsafe)
        log.info("Application window ready")

    # ------------------------------------------------------------------ #
    # Safe callback wrapper - never let a button click crash the app
    # ------------------------------------------------------------------ #
    def _safe(self, fn):
        def wrapper(*args, **kwargs):
            try:
                fn(*args, **kwargs)
            except Exception:
                err = traceback.format_exc()
                log.critical("Unhandled error in UI callback:\n%s", err)
                messagebox.showerror(
                    "Something went wrong",
                    "An error occurred, but the app stayed open.\n\n"
                    "Details have been written to the log file and the log panel.",
                )
        return wrapper

    # ------------------------------------------------------------------ #
    # Transfer tab (Wi-Fi web server)
    # ------------------------------------------------------------------ #
    def _build_transfer_tab(self):
        tab = ui_helpers.make_scrollable(self.transfer_tab)

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=10, pady=10)

        self.status_var = tk.StringVar(value="Stopped")
        self.status_label = ttk.Label(top, textvariable=self.status_var, font=("Segoe UI", 11, "bold"))
        self.status_label.pack(side="left")

        self.toggle_btn = ttk.Button(top, text="Start Server", style="Accent.TButton",
                                      command=self._safe(self._toggle_server))
        self.toggle_btn.pack(side="right")

        info = ttk.Frame(tab)
        info.pack(fill="x", padx=10)

        ttk.Label(info, text="Open this on your phone (same Wi-Fi):").pack(anchor="w")
        self.url_var = tk.StringVar(value="(server stopped)")
        url_entry = ttk.Entry(info, textvariable=self.url_var, state="readonly")
        url_entry.pack(fill="x", pady=(2, 10))
        add_context_menu(url_entry)  # Copy only really applies here (read-only), Cut/Paste no-op safely

        self.qr_label = ttk.Label(tab, text="Start the server to generate a QR code", anchor="center")
        self.qr_label.pack(pady=10)

        send_row = ttk.Frame(tab)
        send_row.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(send_row, text="Add Files to Send to Phone...", style="Accent.TButton",
                   command=self._safe(self._add_files_to_share)).pack(side="left")
        ttk.Button(send_row, text="Add Folder to Send to Phone...",
                   command=self._safe(self._add_folder_to_share)).pack(side="left", padx=(6, 0))
        ttk.Button(send_row, text="Open Share Folder",
                   command=self._safe(self._open_share_folder)).pack(side="left", padx=(6, 0))

        clear_row = ttk.Frame(tab)
        clear_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(clear_row, text="History:", foreground=theme.TEXT_MUTED).pack(side="left")
        ttk.Button(clear_row, text="Clear Received Files...",
                   command=self._safe(self._clear_received_files)).pack(side="left", padx=(6, 0))
        ttk.Button(clear_row, text="Clear Share Folder...",
                   command=self._safe(self._clear_share_folder)).pack(side="left", padx=(6, 0))
        ttk.Button(clear_row, text="Clear Text History...",
                   command=self._safe(self._clear_text_history)).pack(side="left", padx=(6, 0))

        recv_frame = ttk.LabelFrame(tab, text="Recently Received Files (double-click to open)")
        recv_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.received_listbox = tk.Listbox(recv_frame, height=6, bg=theme.PANEL, fg=theme.TEXT,
                                            selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT,
                                            relief="flat", highlightthickness=1,
                                            highlightbackground=theme.PANEL_BORDER, font=("Consolas", 9))
        self.received_listbox.pack(fill="x", padx=6, pady=(6, 4))
        self.received_listbox.bind("<Double-Button-1>", self._safe(self._open_selected_received_file))

        recv_btn_row = ttk.Frame(recv_frame)
        recv_btn_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(recv_btn_row, text="Show in Explorer", style="Accent.TButton",
                   command=self._safe(self._show_selected_received_file)).pack(side="left")
        ttk.Button(recv_btn_row, text="Open File",
                   command=self._safe(self._open_selected_received_file)).pack(side="left", padx=(6, 0))

        ttk.Label(tab, text="Live log").pack(anchor="w", padx=10)
        self.log_widget = scrolledtext.ScrolledText(tab, height=10, state="disabled", font=("Consolas", 8))
        self.log_widget.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        theme.style_log_widget(self.log_widget)
        add_context_menu(self.log_widget)  # Copy the log text; Cut/Paste safely no-op since it's read-only

    def _toggle_server(self):
        if self.server.is_running:
            self.server.stop()
            self.status_var.set("Stopped")
            self.toggle_btn.config(text="Start Server")
            self.url_var.set("(server stopped)")
            self.qr_label.config(image="", text="Start the server to generate a QR code")
        else:
            self.server.start()
            ip = net_utils.get_local_ip()
            url = f"http://{ip}:{self.cfg['server_port']}"
            self.url_var.set(url)
            self.status_var.set("Running")
            self.toggle_btn.config(text="Stop Server")
            self._show_qr(url)

    def _show_qr(self, url: str):
        img = qr_helper.make_qr_image(url)
        img = img.resize((300, 300))
        self._qr_photo = ImageTk.PhotoImage(img)
        self.qr_label.config(image=self._qr_photo, text="")

    def _add_files_to_share(self):
        """One-click laptop -> phone: copy chosen files into the Share
        folder so they immediately show up on the phone's file list."""
        paths = filedialog.askopenfilenames(title="Choose files to make available to your phone")
        if not paths:
            return

        dest_dir = Path(self.cfg["share_folder"])
        dest_dir.mkdir(parents=True, exist_ok=True)

        copied = []
        for p in paths:
            src = Path(p)
            safe_name = safe_filename(src.name)
            dest = self._unique_local_path(dest_dir / safe_name)
            shutil.copy2(src, dest)
            log.info("Added '%s' to Share folder (%.2f MB) for phone download", dest.name,
                      dest.stat().st_size / (1024 * 1024))
            copied.append(dest.name)

        messagebox.showinfo(
            "Ready for your phone",
            f"{len(copied)} file(s) copied to the Share folder.\n\n"
            "Pull to refresh (or tap Refresh) on your phone's page to see them.",
        )

    def _add_folder_to_share(self):
        """One-click laptop -> phone for a WHOLE FOLDER: zips it and drops
        the zip into the Share folder, since the phone's file list is a
        flat list of downloadable files rather than a folder browser."""
        folder = filedialog.askdirectory(title="Choose a folder to send to your phone (it will be zipped)")
        if not folder:
            return

        src = Path(folder)
        dest_dir = Path(self.cfg["share_folder"])
        dest_dir.mkdir(parents=True, exist_ok=True)

        zip_stem = safe_filename(src.name) or "folder"
        dest_zip = self._unique_local_path(dest_dir / f"{zip_stem}.zip")
        base_no_ext = str(dest_zip)[:-4]  # shutil.make_archive appends ".zip" itself

        messagebox.showinfo("Zipping...", f"Zipping '{src.name}' in the background.\n"
                                            "You'll get a confirmation once it's ready.")
        threading.Thread(target=self._zip_folder_thread, args=(src, base_no_ext), daemon=True).start()

    def _zip_folder_thread(self, src: Path, base_no_ext: str):
        try:
            log.info("Zipping folder '%s' for phone...", src)
            start = time.time()
            archive_path = Path(shutil.make_archive(base_no_ext, "zip", root_dir=str(src.parent), base_dir=src.name))
            elapsed = time.time() - start
            size_mb = archive_path.stat().st_size / (1024 * 1024)
            log.info("Zipped '%s' -> '%s' (%.2f MB) in %.2fs", src.name, archive_path.name, size_mb, elapsed)
            self.root.after(0, lambda: messagebox.showinfo(
                "Ready for your phone",
                f"Folder zipped as '{archive_path.name}' ({size_mb:.1f} MB).\n\n"
                "Refresh the phone page to download it.",
            ))
        except (OSError, shutil.Error) as exc:
            log.error("Failed zipping folder '%s': %s", src, exc, exc_info=True)
            self.root.after(0, lambda: messagebox.showerror(
                "Zip failed", f"Could not zip that folder:\n{exc}"))

    def _open_share_folder(self):
        """Open the Share folder in Windows Explorer, for anyone who'd
        rather just drag files in directly instead of using the button."""
        dest_dir = Path(self.cfg["share_folder"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(dest_dir)  # Windows-only, matches this app's target OS
        except (AttributeError, OSError) as exc:
            log.error("Could not open Share folder in Explorer: %s", exc, exc_info=True)
            messagebox.showerror("Couldn't open folder", f"Folder is at:\n{dest_dir}")

    @staticmethod
    def _folder_summary(folder: Path) -> tuple:
        """Returns (file_count, size_mb) - used to show what a Clear
        button is actually about to delete, before doing it."""
        count = 0
        size = 0
        if folder.exists():
            for f in folder.rglob("*"):
                if f.is_file():
                    count += 1
                    size += f.stat().st_size
        return count, size / (1024 * 1024)

    @staticmethod
    def _clear_folder_contents(folder: Path) -> None:
        if not folder.exists():
            return
        for item in folder.iterdir():
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item, ignore_errors=True)
            else:
                try:
                    item.unlink()
                except OSError:
                    pass  # e.g. a file in use - skip rather than crash the clear operation

    def _clear_received_files(self):
        folder = Path(self.cfg["download_folder"])
        count, size_mb = self._folder_summary(folder)
        if count == 0:
            messagebox.showinfo("Nothing to clear", "The received-files folder is already empty.")
            return
        if not messagebox.askyesno(
            "Clear received files?",
            f"This will permanently delete {count} file(s) ({size_mb:.1f} MB) from:\n{folder}\n\n"
            "This cannot be undone. Continue?",
        ):
            return
        self._clear_folder_contents(folder)
        log.info("Cleared %d file(s) (%.1f MB) from download folder", count, size_mb)
        messagebox.showinfo("Cleared", f"Removed {count} file(s).")

    def _clear_share_folder(self):
        folder = Path(self.cfg["share_folder"])
        count, size_mb = self._folder_summary(folder)
        if count == 0:
            messagebox.showinfo("Nothing to clear", "The share folder is already empty.")
            return
        if not messagebox.askyesno(
            "Clear share folder?",
            f"This will permanently delete {count} file(s) ({size_mb:.1f} MB) from:\n{folder}\n\n"
            "Your phone will no longer be able to download these. Continue?",
        ):
            return
        self._clear_folder_contents(folder)
        log.info("Cleared %d file(s) (%.1f MB) from share folder", count, size_mb)
        messagebox.showinfo("Cleared", f"Removed {count} file(s).")

    def _clear_text_history(self):
        if not messagebox.askyesno(
            "Clear text history?",
            "This clears all received/sent text history shown in the Text tab. Continue?",
        ):
            return
        self.server.text_store.clear()
        self._text_entries = []
        self.text_listbox.delete(0, "end")
        self.text_preview.config(state="normal")
        self.text_preview.delete("1.0", "end")
        self.text_preview.config(state="disabled")
        log.info("Cleared text history")

    @staticmethod
    def _unique_local_path(path: Path) -> Path:
        """Avoid overwriting an existing file: file.txt -> file (1).txt, etc."""
        if not path.exists():
            return path
        stem, suffix = path.stem, path.suffix
        parent = path.parent
        i = 1
        while True:
            candidate = parent / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                return candidate
            i += 1

    def _append_log_threadsafe(self, line: str):
        # Log callbacks can arrive from the Flask thread; Tkinter widgets must
        # only be touched from the main thread, so hop over via `after`.
        def do_append():
            self.log_widget.config(state="normal")
            self.log_widget.insert("end", line + "\n")
            self.log_widget.see("end")
            self.log_widget.config(state="disabled")
        try:
            self.root.after(0, do_append)
        except RuntimeError:
            pass  # window already destroyed

    # ------------------------------------------------------------------ #
    # Text tab (share text of any length, either direction)
    # ------------------------------------------------------------------ #
    def _build_text_tab(self):
        tab = ui_helpers.make_scrollable(self.text_tab)
        self._text_entries = []  # newest-first, index matches self.text_listbox rows

        send_frame = ttk.LabelFrame(tab, text="Send text to phone")
        send_frame.pack(fill="both", expand=False, padx=10, pady=(10, 6))

        self.send_text_widget = scrolledtext.ScrolledText(send_frame, height=6, font=("Consolas", 9), wrap="word")
        self.send_text_widget.pack(fill="both", expand=True, padx=6, pady=6)
        theme.style_log_widget(self.send_text_widget)
        wire_field(self.send_text_widget, enter_to_next=False)  # Enter should type a newline here, not tab away

        ttk.Button(send_frame, text="Send to Phone", style="Accent.TButton",
                   command=self._safe(self._send_text_to_phone)).pack(anchor="e", padx=6, pady=(0, 6))

        recv_frame = ttk.LabelFrame(tab, text="Received from phone (newest first)")
        recv_frame.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self.text_listbox = tk.Listbox(recv_frame, height=5, bg=theme.PANEL, fg=theme.TEXT,
                                        selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT,
                                        relief="flat", highlightthickness=1,
                                        highlightbackground=theme.PANEL_BORDER, font=("Consolas", 9))
        self.text_listbox.pack(fill="x", padx=6, pady=(6, 4))
        self.text_listbox.bind("<<ListboxSelect>>", self._safe(self._on_text_select))

        self.text_preview = scrolledtext.ScrolledText(recv_frame, height=7, state="disabled",
                                                        font=("Consolas", 9), wrap="word")
        self.text_preview.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        theme.style_log_widget(self.text_preview)
        add_context_menu(self.text_preview)

        btn_row = ttk.Frame(recv_frame)
        btn_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_row, text="Copy", style="Accent.TButton",
                   command=self._safe(self._copy_selected_text)).pack(side="left")
        ttk.Button(btn_row, text="Save As...",
                   command=self._safe(self._save_selected_text)).pack(side="left", padx=(6, 0))

    def _send_text_to_phone(self):
        content = self.send_text_widget.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showwarning("Nothing to send", "Type some text first.")
            return
        self.server.text_store.add_to_phone(content)
        log.info("Queued text for phone (%d characters)", len(content))
        self.send_text_widget.delete("1.0", "end")
        messagebox.showinfo("Sent", "Text is ready for your phone.\nRefresh the phone page to see it.")

    def _on_text_received_threadsafe(self, entry: dict):
        # Called from the Flask thread when the phone sends text; hop over
        # to the main thread before touching any Tkinter widget.
        def do_add():
            self._text_entries.insert(0, entry)
            del self._text_entries[200:]  # cap growth over long-running sessions (days, not just hours)
            ts = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
            preview = entry["text"].replace("\n", " ").replace("\r", "")[:60]
            suffix = "..." if len(entry["text"]) > 60 else ""
            self.text_listbox.insert(0, f"{ts}  ({len(entry['text'])} chars)  {preview}{suffix}")
            if self.text_listbox.size() > 200:
                self.text_listbox.delete(200, "end")
            self.text_listbox.selection_clear(0, "end")
            self.text_listbox.selection_set(0)
            self._on_text_select()
        try:
            self.root.after(0, do_add)
        except RuntimeError:
            pass  # window already destroyed

    def _on_file_received_threadsafe(self, path: Path):
        # Called from the Flask thread when a file finishes uploading from
        # the phone; hop over to the main thread before touching Tkinter.
        def do_add():
            self._received_files.insert(0, path)
            del self._received_files[200:]  # cap growth over long-running sessions
            try:
                size_mb = path.stat().st_size / (1024 * 1024)
            except OSError:
                size_mb = 0.0
            ts = time.strftime("%H:%M:%S")
            self.received_listbox.insert(0, f"{ts}  ({size_mb:.1f} MB)  {path.name}")
            if self.received_listbox.size() > 200:
                self.received_listbox.delete(200, "end")
            self.received_listbox.selection_clear(0, "end")
            self.received_listbox.selection_set(0)
        try:
            self.root.after(0, do_add)
        except RuntimeError:
            pass  # window already destroyed

    def _selected_received_path(self):
        sel = self.received_listbox.curselection()
        if not sel or sel[0] >= len(self._received_files):
            messagebox.showwarning("Nothing selected", "Select a received file from the list first.")
            return None
        path = self._received_files[sel[0]]
        if not path.exists():
            messagebox.showwarning("File not found", f"This file no longer exists:\n{path}\n\n"
                                                        "It may have been moved or cleared already.")
            return None
        return path

    def _show_selected_received_file(self):
        path = self._selected_received_path()
        if not path:
            return
        try:
            # /select, highlights the exact file in Explorer instead of just
            # opening its containing folder - much faster to spot than
            # having to hunt for it yourself.
            subprocess.Popen(["explorer", "/select,", str(path)])
            log.info("Showed '%s' in Explorer", path.name)
        except OSError as exc:
            log.error("Could not open Explorer for '%s': %s", path, exc, exc_info=True)
            messagebox.showerror("Couldn't open Explorer", f"File is at:\n{path}")

    def _open_selected_received_file(self, event=None):
        path = self._selected_received_path()
        if not path:
            return
        try:
            os.startfile(path)  # opens with whatever app Windows has associated with this file type
            log.info("Opened '%s' with its default app", path.name)
        except OSError as exc:
            log.error("Could not open '%s': %s", path, exc, exc_info=True)
            messagebox.showerror("Couldn't open file", f"File is at:\n{path}")

    def _on_text_select(self, event=None):
        sel = self.text_listbox.curselection()
        if not sel or sel[0] >= len(self._text_entries):
            return
        content = self._text_entries[sel[0]]["text"]
        self.text_preview.config(state="normal")
        self.text_preview.delete("1.0", "end")
        self.text_preview.insert("1.0", content)
        self.text_preview.config(state="disabled")

    def _copy_selected_text(self):
        content = self.text_preview.get("1.0", "end-1c")
        if not content:
            messagebox.showwarning("Nothing to copy", "Select a received text first.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        log.info("Copied received text to clipboard (%d characters)", len(content))

    def _save_selected_text(self):
        content = self.text_preview.get("1.0", "end-1c")
        if not content:
            messagebox.showwarning("Nothing to save", "Select a received text first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save text as...",
            defaultextension=".txt",
            filetypes=[
                ("Text file", "*.txt"),
                ("Python file", "*.py"),
                ("Batch file", "*.bat"),
                ("Markdown file", "*.md"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            log.info("Saved received text to '%s' (%d characters)", path, len(content))
            messagebox.showinfo("Saved", f"Saved to:\n{path}")
        except OSError as exc:
            log.error("Failed saving text to '%s': %s", path, exc, exc_info=True)
            messagebox.showerror("Save failed", str(exc))

    # ------------------------------------------------------------------ #
    # Screen Mirror tab (optional, via scrcpy)
    # ------------------------------------------------------------------ #
    def _build_mirror_tab(self):
        tab = ui_helpers.make_scrollable(self.mirror_tab)
        ttk.Label(
            tab,
            text="See and control your phone from the laptop with the mouse - open apps,\n"
                 "drag files onto the mirror window to send them, and use a file manager\n"
                 "app on the phone (through the mirror) to move/copy/delete things.\n\n"
                 "This uses scrcpy, a free open-source tool, over the same ADB connection\n"
                 "as the ADB tab. Requires a USB (or wireless ADB) connection.",
            wraplength=520, justify="left",
        ).pack(anchor="w", padx=10, pady=10)

        check_row = ttk.Frame(tab)
        check_row.pack(fill="x", padx=10)
        ttk.Button(check_row, text="Check scrcpy", command=self._safe(self._check_scrcpy)).pack(side="left")
        ttk.Button(check_row, text="Check ADB", command=self._safe(self._check_adb)).pack(side="left", padx=6)
        ttk.Button(check_row, text="List Devices", command=self._safe(self._list_adb_devices)).pack(side="left")
        self.mirror_status_var = tk.StringVar(value="Not checked yet")
        ttk.Label(tab, textvariable=self.mirror_status_var, foreground=theme.TEXT_MUTED).pack(
            anchor="w", padx=10, pady=(4, 10))

        perf = ttk.LabelFrame(tab, text="Performance (tuned conservatively for older/integrated graphics)")
        perf.pack(fill="x", padx=10, pady=(0, 10))

        row1 = ttk.Frame(perf)
        row1.pack(fill="x", padx=6, pady=6)
        ttk.Label(row1, text="Max size (px):").pack(side="left")
        self.mirror_max_size_var = tk.StringVar(value=str(self.cfg.get("scrcpy_max_size", 800)))
        e1 = ttk.Entry(row1, textvariable=self.mirror_max_size_var, width=8)
        e1.pack(side="left", padx=(4, 16))
        wire_field(e1)
        ttk.Label(row1, text="Bitrate (Mbps):").pack(side="left")
        self.mirror_bitrate_var = tk.StringVar(value=str(self.cfg.get("scrcpy_bitrate_mbps", 4)))
        e2 = ttk.Entry(row1, textvariable=self.mirror_bitrate_var, width=6)
        e2.pack(side="left", padx=(4, 16))
        wire_field(e2)
        ttk.Label(row1, text="Max FPS:").pack(side="left")
        self.mirror_fps_var = tk.StringVar(value=str(self.cfg.get("scrcpy_max_fps", 30)))
        e3 = ttk.Entry(row1, textvariable=self.mirror_fps_var, width=6)
        e3.pack(side="left", padx=(4, 0))
        wire_field(e3)

        self.mirror_screen_off_var = tk.BooleanVar(value=self.cfg.get("scrcpy_turn_screen_off", False))
        ttk.Checkbutton(perf, text="Turn phone screen off while mirroring (saves battery)",
                         variable=self.mirror_screen_off_var).pack(anchor="w", padx=6, pady=(0, 6))

        ttk.Button(tab, text="Start Mirroring", style="Accent.TButton",
                   command=self._safe(self._start_mirroring)).pack(anchor="w", padx=10, pady=(0, 10))

    def _check_scrcpy(self):
        installed = scrcpy_helper.is_installed(self.cfg["scrcpy_path"])
        self.mirror_status_var.set("scrcpy found" if installed else
                                    "scrcpy not found - install it and set the path in Settings")

    def _save_mirror_settings_from_fields(self):
        """Pull the performance fields into cfg before launching (doesn't
        require pressing Save Settings first - these are quick-tune fields)."""
        try:
            self.cfg["scrcpy_max_size"] = int(self.mirror_max_size_var.get().strip())
            self.cfg["scrcpy_bitrate_mbps"] = int(self.mirror_bitrate_var.get().strip())
            self.cfg["scrcpy_max_fps"] = int(self.mirror_fps_var.get().strip())
        except ValueError:
            pass  # keep previous values if the user typed something invalid
        self.cfg["scrcpy_turn_screen_off"] = bool(self.mirror_screen_off_var.get())
        self.save_cfg(self.cfg)

    def _start_mirroring(self):
        self._save_mirror_settings_from_fields()
        self.mirror_status_var.set("Launching scrcpy...")
        threading.Thread(target=self._start_mirroring_thread, daemon=True).start()

    def _start_mirroring_thread(self):
        ok, msg = scrcpy_helper.launch(self.cfg["scrcpy_path"], self.cfg)
        text = "Mirroring window opened" if ok else f"Failed: {msg}"
        self.root.after(0, lambda: self.mirror_status_var.set(text))

    # ------------------------------------------------------------------ #
    # Public Access tab (optional, via the user's existing Tailscale
    # Funnel publisher - this app deliberately does NOT call tailscale.exe
    # itself, so every tool the user publishes goes through the same
    # already-working script instead of a second, inconsistent one)
    # ------------------------------------------------------------------ #
    def _build_public_tab(self):
        tab = ui_helpers.make_scrollable(self.public_tab)
        ttk.Label(
            tab,
            text="Publish this tool to the public internet, so you can use it from\n"
                 "anywhere - not just your home Wi-Fi. This uses your existing Tailscale\n"
                 "Funnel publisher script rather than a separate one, so it works exactly\n"
                 "like every other tool you've published.",
            wraplength=520, justify="left",
        ).pack(anchor="w", padx=10, pady=10)

        port_frame = ttk.LabelFrame(tab, text="Step 1: give this port to your publisher script")
        port_frame.pack(fill="x", padx=10, pady=(0, 10))
        port_row = ttk.Frame(port_frame)
        port_row.pack(fill="x", padx=6, pady=6)
        ttk.Label(port_row, text="This tool's local port:").pack(side="left")
        self.public_port_var = tk.StringVar(value=str(self.cfg.get("server_port", 8765)))
        port_display = ttk.Entry(port_row, textvariable=self.public_port_var, state="readonly", width=8)
        port_display.pack(side="left", padx=(6, 6))
        add_context_menu(port_display)
        ttk.Button(port_row, text="Copy", command=self._safe(self._copy_local_port)).pack(side="left")
        ttk.Label(port_frame, text="(Make sure Start Server is on in the Wi-Fi Transfer tab first.)",
                  foreground=theme.TEXT_MUTED).pack(anchor="w", padx=6, pady=(0, 6))

        launch_frame = ttk.LabelFrame(tab, text="Step 2: run your publisher")
        launch_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(launch_frame, text="Open PUBLISH-TOOL.bat", style="Accent.TButton",
                   command=self._safe(self._open_publisher_tool)).pack(anchor="w", padx=6, pady=6)
        ttk.Label(
            launch_frame,
            text="Opens your universal publisher in its own window. Choose 'publish new\n"
                 "tool', give it the port above and a name (e.g. transfer-tool), and pick\n"
                 "a free slot (443 / 8443 / 10000).",
            wraplength=500, justify="left", foreground=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=6, pady=(0, 6))

        url_frame = ttk.LabelFrame(tab, text="Step 3: paste the URL it gives you")
        url_frame.pack(fill="x", padx=10, pady=(0, 10))
        url_row = ttk.Frame(url_frame)
        url_row.pack(fill="x", padx=6, pady=6)
        self.public_url_var = tk.StringVar(value="")
        public_url_entry = ttk.Entry(url_row, textvariable=self.public_url_var)
        public_url_entry.pack(side="left", fill="x", expand=True)
        wire_field(public_url_entry)
        ttk.Button(url_row, text="Show QR", style="Accent.TButton",
                   command=self._safe(self._show_public_qr)).pack(side="left", padx=(6, 0))

        self.public_qr_label = ttk.Label(tab, text="", anchor="center")
        self.public_qr_label.pack(pady=10)

        pin_frame = ttk.LabelFrame(tab, text="Access PIN (recommended before publishing)")
        pin_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(
            pin_frame,
            text="Without a PIN, anyone with the public URL can upload/download files or\n"
                 "read/send text \u2014 there's no other login. Turning this on asks for a PIN\n"
                 "once per browser session (on your phone too, including on local Wi-Fi).",
            wraplength=500, justify="left",
        ).pack(anchor="w", padx=6, pady=(6, 6))

        self.require_pin_var = tk.BooleanVar(value=self.cfg.get("require_access_pin", False))
        ttk.Checkbutton(pin_frame, text="Require PIN to access this tool", variable=self.require_pin_var,
                         command=self._safe(self._toggle_require_pin)).pack(anchor="w", padx=6)

        pin_row = ttk.Frame(pin_frame)
        pin_row.pack(fill="x", padx=6, pady=(4, 6))
        ttk.Label(pin_row, text="Current PIN:").pack(side="left")
        self.access_pin_var = tk.StringVar(value=self.cfg.get("access_pin", ""))
        pin_entry = ttk.Entry(pin_row, textvariable=self.access_pin_var, state="readonly", width=12)
        pin_entry.pack(side="left", padx=(6, 6))
        add_context_menu(pin_entry)
        ttk.Button(pin_row, text="Generate New PIN",
                   command=self._safe(self._generate_new_pin)).pack(side="left")

    def _copy_local_port(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.public_port_var.get())

    def _open_publisher_tool(self):
        bat_path = Path(self.cfg.get("tailscale_publisher_path", ""))
        if not bat_path.is_file():
            messagebox.showerror(
                "Not found",
                f"Couldn't find your publisher script at:\n{bat_path}\n\n"
                "Set the correct path in the Settings tab (Tailscale Publisher script).",
            )
            log.warning("PUBLISH-TOOL.bat not found at configured path: %s", bat_path)
            return
        try:
            os.startfile(bat_path)  # opens it in its own console window, same as double-clicking it
            log.info("Launched publisher script: %s", bat_path)
        except OSError as exc:
            log.error("Could not launch publisher script: %s", exc, exc_info=True)
            messagebox.showerror("Couldn't launch", f"Could not open {bat_path.name}:\n{exc}")

    def _show_public_qr(self):
        url = self.public_url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL yet", "Paste the URL your publisher script gave you first.")
            return
        if not url.startswith("http"):
            url = "https://" + url
        img = qr_helper.make_qr_image(url)
        img = img.resize((240, 240))
        self._public_qr_photo = ImageTk.PhotoImage(img)
        self.public_qr_label.config(image=self._public_qr_photo, text="")
        log.info("Generated QR code for public URL")

    def _toggle_require_pin(self):
        enabled = bool(self.require_pin_var.get())
        if enabled and not self.cfg.get("access_pin"):
            self._generate_new_pin(save=False)  # ensure a PIN exists before turning this on
        self.cfg["require_access_pin"] = enabled
        self.save_cfg(self.cfg)
        log.info("Access PIN requirement %s", "enabled" if enabled else "disabled")

    def _generate_new_pin(self, save: bool = True):
        import secrets
        new_pin = f"{secrets.randbelow(1_000_000):06d}"
        self.cfg["access_pin"] = new_pin
        self.access_pin_var.set(new_pin)
        if save:
            self.save_cfg(self.cfg)
        log.info("Generated a new access PIN")

    # ------------------------------------------------------------------ #
    # Shared Rooms tab (optional) - lets strangers with a link pair their
    # OWN laptop + phone via an isolated room, separate from the owner's
    # personal share. Off by default - see room_manager.py for why.
    # ------------------------------------------------------------------ #
    def _build_rooms_tab(self):
        tab = ui_helpers.make_scrollable(self.rooms_tab)
        ttk.Label(
            tab,
            text="Let anyone with a link pair their OWN laptop and phone through this\n"
                 "app, without touching your personal files. Each visitor gets an\n"
                 "isolated room (own files, own text) that expires automatically.\n"
                 "Off by default \u2014 turning this on means anyone with the link below\n"
                 "can use your PC's storage and bandwidth temporarily.",
            wraplength=520, justify="left",
        ).pack(anchor="w", padx=10, pady=10)

        self.rooms_enabled_var = tk.BooleanVar(value=self.cfg.get("rooms_enabled", False))
        ttk.Checkbutton(tab, text="Enable Shared Rooms", variable=self.rooms_enabled_var,
                         command=self._safe(self._toggle_rooms_enabled)).pack(anchor="w", padx=10)

        limits = ttk.LabelFrame(tab, text="Safety limits")
        limits.pack(fill="x", padx=10, pady=10)
        row1 = ttk.Frame(limits)
        row1.pack(fill="x", padx=6, pady=6)
        ttk.Label(row1, text="Auto-delete a room after (hours):").pack(side="left")
        self.room_max_age_var = tk.StringVar(value=str(self.cfg.get("room_max_age_hours", 24)))
        e1 = ttk.Entry(row1, textvariable=self.room_max_age_var, width=6)
        e1.pack(side="left", padx=(4, 16))
        wire_field(e1)
        ttk.Label(row1, text="Max file size per room (MB):").pack(side="left")
        self.room_max_mb_var = tk.StringVar(value=str(self.cfg.get("room_max_file_mb", 500)))
        e2 = ttk.Entry(row1, textvariable=self.room_max_mb_var, width=8)
        e2.pack(side="left", padx=(4, 0))
        wire_field(e2)
        ttk.Button(limits, text="Save Limits", style="Accent.TButton",
                   command=self._safe(self._save_room_limits)).pack(anchor="w", padx=6, pady=(0, 6))

        links = ttk.LabelFrame(tab, text="Link to share with someone")
        links.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(links, text="On the same Wi-Fi:").pack(anchor="w", padx=6, pady=(6, 0))
        lan_row = ttk.Frame(links)
        lan_row.pack(fill="x", padx=6, pady=(0, 6))
        self.rooms_lan_link_var = tk.StringVar(value="")
        lan_entry = ttk.Entry(lan_row, textvariable=self.rooms_lan_link_var, state="readonly")
        lan_entry.pack(side="left", fill="x", expand=True)
        add_context_menu(lan_entry)
        ttk.Button(lan_row, text="Copy", command=self._safe(
            lambda: self._copy_text_var(self.rooms_lan_link_var))).pack(side="left", padx=(6, 0))

        ttk.Label(links, text="From anywhere (needs Public Access set up first):").pack(
            anchor="w", padx=6, pady=(0, 0))
        pub_row = ttk.Frame(links)
        pub_row.pack(fill="x", padx=6, pady=(0, 6))
        self.rooms_public_link_var = tk.StringVar(value="")
        pub_entry = ttk.Entry(pub_row, textvariable=self.rooms_public_link_var, state="readonly")
        pub_entry.pack(side="left", fill="x", expand=True)
        add_context_menu(pub_entry)
        ttk.Button(pub_row, text="Copy", command=self._safe(
            lambda: self._copy_text_var(self.rooms_public_link_var))).pack(side="left", padx=(6, 0))
        ttk.Button(links, text="Refresh Links", command=self._safe(self._refresh_room_links)).pack(
            anchor="w", padx=6, pady=(0, 6))

        active = ttk.LabelFrame(tab, text="Active rooms")
        active.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        btn_row = ttk.Frame(active)
        btn_row.pack(fill="x", padx=6, pady=6)
        ttk.Button(btn_row, text="Refresh List", command=self._safe(self._refresh_active_rooms)).pack(side="left")
        ttk.Button(btn_row, text="Delete Selected", command=self._safe(self._delete_selected_room)).pack(
            side="left", padx=6)
        ttk.Button(btn_row, text="Delete All", command=self._safe(self._delete_all_rooms)).pack(side="left")

        self.rooms_listbox = tk.Listbox(active, height=6, bg=theme.PANEL, fg=theme.TEXT,
                                         selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT,
                                         relief="flat", highlightthickness=1,
                                         highlightbackground=theme.PANEL_BORDER, font=("Consolas", 9))
        self.rooms_listbox.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._refresh_room_links()
        self._refresh_active_rooms()

    def _toggle_rooms_enabled(self):
        self.cfg["rooms_enabled"] = bool(self.rooms_enabled_var.get())
        self.save_cfg(self.cfg)
        log.info("Shared Rooms %s", "enabled" if self.cfg["rooms_enabled"] else "disabled")

    def _save_room_limits(self):
        try:
            self.cfg["room_max_age_hours"] = float(self.room_max_age_var.get().strip())
            self.cfg["room_max_file_mb"] = float(self.room_max_mb_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid value", "Room age and size limit must be numbers.")
            return
        self.save_cfg(self.cfg)
        log.info("Room limits saved: max_age_hours=%s max_file_mb=%s",
                  self.cfg["room_max_age_hours"], self.cfg["room_max_file_mb"])

    def _copy_text_var(self, string_var: tk.StringVar):
        value = string_var.get()
        if not value:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)

    def _refresh_room_links(self):
        ip = net_utils.get_local_ip()
        port = self.cfg.get("server_port", 8765)
        self.rooms_lan_link_var.set(f"http://{ip}:{port}/room")
        public_base = self.public_url_var.get().strip() if hasattr(self, "public_url_var") else ""
        if public_base:
            self.rooms_public_link_var.set(public_base.rstrip("/") + "/room")
        else:
            self.rooms_public_link_var.set("(set up Public Access first, then Refresh Links)")

    def _refresh_active_rooms(self):
        self.rooms_listbox.delete(0, "end")
        rooms = room_manager.list_active_rooms()
        if not rooms:
            self.rooms_listbox.insert("end", "  No active rooms")
            return
        for r in rooms:
            age_min = int((time.time() - r["last_activity"]) / 60)
            self.rooms_listbox.insert(
                "end",
                f"  {r['code']}   {r['file_count']} file(s)   {r['size_mb']:.1f} MB   "
                f"last active {age_min} min ago"
            )

    def _delete_selected_room(self):
        sel = self.rooms_listbox.curselection()
        if not sel:
            messagebox.showwarning("Nothing selected", "Select a room from the list first.")
            return
        line = self.rooms_listbox.get(sel[0]).strip()
        if not line or line.startswith("No active"):
            return
        code = line.split()[0]
        room_manager.delete_room(code)
        self._refresh_active_rooms()

    def _delete_all_rooms(self):
        n = room_manager.delete_all_rooms()
        log.info("Deleted all %d active room(s) from the GUI", n)
        self._refresh_active_rooms()

    # ------------------------------------------------------------------ #
    # ADB tab (optional)
    # ------------------------------------------------------------------ #
    def _build_adb_tab(self):
        tab = ui_helpers.make_scrollable(self.adb_tab)
        ttk.Label(
            tab,
            text="Optional: faster direct transfer over USB (or wireless ADB) for Android.\n"
                 "Requires Android platform-tools (adb) installed separately.",
            wraplength=500, justify="left",
        ).pack(anchor="w", padx=10, pady=10)

        check_row = ttk.Frame(tab)
        check_row.pack(fill="x", padx=10)
        ttk.Button(check_row, text="Check ADB", command=self._safe(self._check_adb)).pack(side="left")
        ttk.Button(check_row, text="List Devices", command=self._safe(self._list_adb_devices)).pack(
            side="left", padx=6)
        self.adb_status_var = tk.StringVar(value="Not checked yet")
        ttk.Label(check_row, textvariable=self.adb_status_var).pack(side="left", padx=10)

        # Push section
        push_frame = ttk.LabelFrame(tab, text="Send file/folder to phone (push)")
        push_frame.pack(fill="x", padx=10, pady=10)
        self.push_local_var = tk.StringVar()
        push_local_entry = ttk.Entry(push_frame, textvariable=self.push_local_var)
        push_local_entry.pack(fill="x", padx=6, pady=(6, 2))
        wire_field(push_local_entry)
        ttk.Button(push_frame, text="Browse local file/folder...",
                   command=self._safe(self._browse_push_local)).pack(anchor="w", padx=6)
        ttk.Label(push_frame, text="Destination on phone:").pack(anchor="w", padx=6, pady=(6, 0))
        self.push_remote_var = tk.StringVar(value=adb_helper.COMMON_PHONE_PATHS[0])
        remote_combo = ttk.Combobox(push_frame, textvariable=self.push_remote_var,
                                     values=adb_helper.COMMON_PHONE_PATHS)
        remote_combo.pack(fill="x", padx=6, pady=(0, 6))
        wire_field(remote_combo)
        ttk.Button(push_frame, text="Push to Phone", style="Accent.TButton",
                   command=self._safe(self._do_push)).pack(anchor="e", padx=6, pady=(0, 6))

        # Pull section
        pull_frame = ttk.LabelFrame(tab, text="Get file/folder from phone (pull)")
        pull_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(pull_frame, text="Source on phone:").pack(anchor="w", padx=6, pady=(6, 0))
        self.pull_remote_var = tk.StringVar(value=adb_helper.COMMON_PHONE_PATHS[0])
        pull_combo = ttk.Combobox(pull_frame, textvariable=self.pull_remote_var,
                                   values=adb_helper.COMMON_PHONE_PATHS)
        pull_combo.pack(fill="x", padx=6, pady=(0, 6))
        wire_field(pull_combo)
        self.pull_local_var = tk.StringVar(value=self.cfg["download_folder"])
        pull_local_entry = ttk.Entry(pull_frame, textvariable=self.pull_local_var)
        pull_local_entry.pack(fill="x", padx=6, pady=(0, 2))
        wire_field(pull_local_entry)
        ttk.Button(pull_frame, text="Browse local destination...",
                   command=self._safe(self._browse_pull_local)).pack(anchor="w", padx=6)
        ttk.Button(pull_frame, text="Pull from Phone", style="Accent.TButton",
                   command=self._safe(self._do_pull)).pack(anchor="e", padx=6, pady=(6, 6))

    def _check_adb(self):
        ok, msg = adb_helper.check_adb_available(self.cfg["adb_path"])
        self.adb_status_var.set(("OK: " if ok else "Not available: ") + msg)

    def _list_adb_devices(self):
        ok, devices, msg = adb_helper.list_devices(self.cfg["adb_path"])
        if not ok:
            self.adb_status_var.set("Error: " + msg)
            return
        self.adb_status_var.set(f"{len(devices)} device(s): {', '.join(devices) or 'none connected'}")

    def _browse_push_local(self):
        path = filedialog.askopenfilename(title="Choose a file to push")
        if not path:
            path = filedialog.askdirectory(title="...or choose a folder to push")
        if path:
            self.push_local_var.set(path)

    def _browse_pull_local(self):
        path = filedialog.askdirectory(title="Choose where to save pulled files")
        if path:
            self.pull_local_var.set(path)

    def _do_push(self):
        local = self.push_local_var.get().strip()
        remote = self.push_remote_var.get().strip()
        if not local or not remote:
            messagebox.showwarning("Missing info", "Pick a local file/folder and a phone destination first.")
            return
        threading.Thread(target=self._run_push_thread, args=(local, remote), daemon=True).start()

    def _run_push_thread(self, local, remote):
        ok, output = adb_helper.push(self.cfg["adb_path"], local, remote,
                                      progress_cb=lambda line: log.debug("push: %s", line))
        self.root.after(0, lambda: self.adb_status_var.set("Push complete" if ok else f"Push failed: {output[:200]}"))

    def _do_pull(self):
        remote = self.pull_remote_var.get().strip()
        local = self.pull_local_var.get().strip()
        if not local or not remote:
            messagebox.showwarning("Missing info", "Pick a phone source and a local destination first.")
            return
        threading.Thread(target=self._run_pull_thread, args=(remote, local), daemon=True).start()

    def _run_pull_thread(self, remote, local):
        ok, output = adb_helper.pull(self.cfg["adb_path"], remote, local,
                                      progress_cb=lambda line: log.debug("pull: %s", line))
        self.root.after(0, lambda: self.adb_status_var.set("Pull complete" if ok else f"Pull failed: {output[:200]}"))

    # ------------------------------------------------------------------ #
    # Auto-Sync tab (optional, Syncthing launcher)
    # ------------------------------------------------------------------ #
    def _build_sync_tab(self):
        tab = ui_helpers.make_scrollable(self.sync_tab)
        ttk.Label(
            tab,
            text="Optional: Syncthing keeps chosen folders continuously synced in the\n"
                 "background between phone and laptop \u2014 no manual transfer needed once\n"
                 "it's paired. This app just launches it; setup/pairing happens in\n"
                 "Syncthing's own web UI (one-time).",
            wraplength=500, justify="left",
        ).pack(anchor="w", padx=10, pady=10)

        row = ttk.Frame(tab)
        row.pack(fill="x", padx=10, pady=6)
        ttk.Button(row, text="Check if Installed", command=self._safe(self._check_syncthing)).pack(side="left")
        ttk.Button(row, text="Launch Syncthing", command=self._safe(self._launch_syncthing)).pack(
            side="left", padx=6)
        ttk.Button(row, text="Open Web UI", command=self._safe(self._open_syncthing_ui)).pack(side="left")

        self.sync_status_var = tk.StringVar(value="Not checked yet")
        ttk.Label(tab, textvariable=self.sync_status_var).pack(anchor="w", padx=10, pady=(4, 10))

        ttk.Button(tab, text="Don't have Syncthing? Get it here",
                   command=self._safe(syncthing_helper.open_download_page)).pack(anchor="w", padx=10)

    def _check_syncthing(self):
        installed = syncthing_helper.is_installed(self.cfg["syncthing_path"])
        self.sync_status_var.set("Installed and on PATH" if installed else "Not found on PATH (set path in Settings)")

    def _launch_syncthing(self):
        ok, msg = syncthing_helper.launch_if_not_running(self.cfg["syncthing_path"])
        self.sync_status_var.set(msg)

    def _open_syncthing_ui(self):
        syncthing_helper.open_web_ui(self.cfg["syncthing_web_ui"])

    # ------------------------------------------------------------------ #
    # Settings tab
    # ------------------------------------------------------------------ #
    def _build_settings_tab(self):
        tab = ui_helpers.make_scrollable(self.settings_tab)
        pad = {"padx": 10, "pady": 6}

        ttk.Label(tab, text="Server port:").grid(row=0, column=0, sticky="w", **pad)
        self.port_var = tk.StringVar(value=str(self.cfg["server_port"]))
        port_entry = ttk.Entry(tab, textvariable=self.port_var, width=10)
        port_entry.grid(row=0, column=1, sticky="w", **pad)
        wire_field(port_entry)

        ttk.Label(tab, text="Download folder (phone \u2192 laptop):").grid(row=1, column=0, sticky="w", **pad)
        self.download_var = tk.StringVar(value=self.cfg["download_folder"])
        download_entry = ttk.Entry(tab, textvariable=self.download_var, width=45)
        download_entry.grid(row=1, column=1, sticky="w", **pad)
        wire_field(download_entry)
        ttk.Button(tab, text="Browse...", command=self._safe(
            lambda: self._browse_into(self.download_var))).grid(row=1, column=2, **pad)

        ttk.Label(tab, text="Share folder (laptop \u2192 phone):").grid(row=2, column=0, sticky="w", **pad)
        self.share_var = tk.StringVar(value=self.cfg["share_folder"])
        share_entry = ttk.Entry(tab, textvariable=self.share_var, width=45)
        share_entry.grid(row=2, column=1, sticky="w", **pad)
        wire_field(share_entry)
        ttk.Button(tab, text="Browse...", command=self._safe(
            lambda: self._browse_into(self.share_var))).grid(row=2, column=2, **pad)

        ttk.Label(tab, text="ADB path (if not on PATH):").grid(row=3, column=0, sticky="w", **pad)
        self.adb_path_var = tk.StringVar(value=self.cfg["adb_path"])
        adb_path_entry = ttk.Entry(tab, textvariable=self.adb_path_var, width=45)
        adb_path_entry.grid(row=3, column=1, sticky="w", **pad)
        wire_field(adb_path_entry)

        ttk.Label(tab, text="Syncthing path (if not on PATH):").grid(row=4, column=0, sticky="w", **pad)
        self.syncthing_path_var = tk.StringVar(value=self.cfg["syncthing_path"])
        syncthing_path_entry = ttk.Entry(tab, textvariable=self.syncthing_path_var, width=45)
        syncthing_path_entry.grid(row=4, column=1, sticky="w", **pad)
        wire_field(syncthing_path_entry)

        ttk.Label(tab, text="scrcpy path (if not on PATH):").grid(row=5, column=0, sticky="w", **pad)
        self.scrcpy_path_var = tk.StringVar(value=self.cfg["scrcpy_path"])
        scrcpy_path_entry = ttk.Entry(tab, textvariable=self.scrcpy_path_var, width=45)
        scrcpy_path_entry.grid(row=5, column=1, sticky="w", **pad)
        wire_field(scrcpy_path_entry)

        ttk.Label(tab, text="Tailscale Publisher script:").grid(row=6, column=0, sticky="w", **pad)
        self.tailscale_path_var = tk.StringVar(value=self.cfg["tailscale_publisher_path"])
        tailscale_path_entry = ttk.Entry(tab, textvariable=self.tailscale_path_var, width=45)
        tailscale_path_entry.grid(row=6, column=1, sticky="w", **pad)
        wire_field(tailscale_path_entry)
        ttk.Button(tab, text="Browse...", command=self._safe(
            lambda: self._browse_into_file(self.tailscale_path_var))).grid(row=6, column=2, **pad)

        ttk.Button(tab, text="Save Settings", style="Accent.TButton", command=self._safe(self._save_settings)).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=10, pady=16)

        note = ttk.Label(
            tab,
            text="Note: changing the port or folders takes effect the next time you start the server.\n"
                 "The app's own data (config, logs, default folders) always lives inside this project's\n"
                 "own folder, wherever you placed it \u2014 nothing else is created elsewhere.",
            foreground=theme.TEXT_MUTED, wraplength=480, justify="left",
        )
        note.grid(row=8, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))

    def _browse_into(self, string_var: tk.StringVar):
        path = filedialog.askdirectory(title="Choose folder")
        if path:
            string_var.set(path)

    def _browse_into_file(self, string_var: tk.StringVar):
        path = filedialog.askopenfilename(title="Choose file",
                                           filetypes=[("Batch files", "*.bat"), ("All files", "*.*")])
        if path:
            string_var.set(path)

    def _save_settings(self):
        try:
            port = int(self.port_var.get().strip())
            if not (1 <= port <= 65535):
                raise ValueError("out of range")
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be a number between 1 and 65535.")
            return

        self.cfg["server_port"] = port
        self.cfg["download_folder"] = self.download_var.get().strip() or self.cfg["download_folder"]
        self.cfg["share_folder"] = self.share_var.get().strip() or self.cfg["share_folder"]
        self.cfg["adb_path"] = self.adb_path_var.get().strip() or "adb"
        self.cfg["syncthing_path"] = self.syncthing_path_var.get().strip() or "syncthing"
        self.cfg["scrcpy_path"] = self.scrcpy_path_var.get().strip() or "scrcpy"
        self.cfg["tailscale_publisher_path"] = self.tailscale_path_var.get().strip() or self.cfg["tailscale_publisher_path"]

        Path(self.cfg["download_folder"]).mkdir(parents=True, exist_ok=True)
        Path(self.cfg["share_folder"]).mkdir(parents=True, exist_ok=True)

        self.save_cfg(self.cfg)
        log.info("Settings saved: %s", self.cfg)
        messagebox.showinfo("Saved", "Settings saved. Restart the server for changes to take effect.")

    # ------------------------------------------------------------------ #
    def _on_close(self):
        try:
            if self.server.is_running:
                self.server.stop()
        except Exception:
            log.error("Error while stopping server on close", exc_info=True)
        finally:
            self.root.destroy()

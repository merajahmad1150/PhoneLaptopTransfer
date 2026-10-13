"""
core/gui_transfer.py
The "Wi-Fi Transfer" and "Text" pages of the desktop window.
"""

import os
import shutil
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

import net_utils
import theme
import ui_helpers
import zip_utils
from history_store import KIND_FILE_FROM_PHONE
from logger import get_logger
from qr_helper import make_qr_image
from safe_names import safe_filename

log = get_logger()
wire_field = ui_helpers.wire_field
add_context_menu = ui_helpers.add_context_menu


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class TransferMixin:
    # ------------------------------------------------------------------ #
    # Transfer page
    # ------------------------------------------------------------------ #
    def _build_transfer_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        self._qr_photo = None
        self._received_paths = []

        status = ttk.LabelFrame(tab, text="Server")
        status.pack(fill="x", padx=12, pady=(10, 6))
        row = ttk.Frame(status)
        row.pack(fill="x", padx=8, pady=8)
        self.server_state_var = tk.StringVar(value="Stopped")
        self.server_state_label = ttk.Label(row, textvariable=self.server_state_var, style="Heading.TLabel")
        self.server_state_label.pack(side="left")
        self.toggle_btn = ttk.Button(row, text="Start Server", style="Accent.TButton",
                                     command=self._safe(self._toggle_server))
        self.toggle_btn.pack(side="right")

        link_row = ttk.Frame(status)
        link_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(link_row, text="Phone link (same Wi-Fi):").pack(side="left")
        self.lan_url_var = tk.StringVar()
        e = ttk.Entry(link_row, textvariable=self.lan_url_var, state="readonly")
        e.pack(side="left", fill="x", expand=True, padx=8)
        add_context_menu(e)
        ttk.Button(link_row, text="Copy", command=self._safe(lambda: self._copy_text_var(self.lan_url_var))).pack(side="left")
        ttk.Button(link_row, text="Open", command=self._safe(self._open_lan_url)).pack(side="left", padx=(6, 0))

        pub_row = ttk.Frame(status)
        pub_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(pub_row, text="Public link (internet):").pack(side="left")
        self.transfer_pub_var = tk.StringVar(value="not published yet")
        self.transfer_pub_label = ttk.Label(pub_row, textvariable=self.transfer_pub_var, style="Muted.TLabel")
        self.transfer_pub_label.pack(side="left", padx=8)

        self.qr_label = tk.Label(status, bg=theme.PANEL, bd=0)
        self.qr_label.pack(pady=(4, 10))
        self.qr_caption = ttk.Label(status, text="Start the server, then scan this QR code with your phone camera.",
                                    style="Muted.TLabel")
        self.qr_caption.pack(pady=(0, 8))

        share = ttk.LabelFrame(tab, text="Send to phone  (laptop -> phone)")
        share.pack(fill="x", padx=12, pady=6)
        r1 = ttk.Frame(share)
        r1.pack(fill="x", padx=8, pady=8)
        ttk.Button(r1, text="Add Files...  (Ctrl+O)", style="Accent.TButton",
                   command=self._safe(self._add_files_to_share)).pack(side="left")
        ttk.Button(r1, text="Add Folder...  (Ctrl+Shift+O)", command=self._safe(self._add_folder_to_share)).pack(side="left", padx=6)
        ttk.Button(r1, text="Open Share Folder", command=self._safe(self._open_share_folder)).pack(side="left")
        ttk.Button(r1, text="Clear", style="Danger.TButton", command=self._safe(self._clear_share_folder)).pack(side="right")
        self.share_status_var = tk.StringVar(value="")
        ttk.Label(share, textvariable=self.share_status_var, style="Muted.TLabel").pack(anchor="w", padx=8, pady=(0, 6))

        recv = ttk.LabelFrame(tab, text="Recently received from phone  (double-click to open)")
        recv.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        r2 = ttk.Frame(recv)
        r2.pack(fill="x", padx=8, pady=8)
        ttk.Button(r2, text="Show in Explorer", command=self._safe(self._show_selected_received_file)).pack(side="left")
        ttk.Button(r2, text="Open File", command=self._safe(self._open_selected_received_file)).pack(side="left", padx=6)
        ttk.Button(r2, text="Open Received Folder  (Ctrl+E)", command=self._safe(self._open_received_folder)).pack(side="left")
        ttk.Button(r2, text="Clear", style="Danger.TButton", command=self._safe(self._clear_received_files)).pack(side="right")
        self.received_listbox = tk.Listbox(recv, height=9, bg=theme.PANEL, fg=theme.TEXT, selectbackground=theme.ACCENT,
                                           selectforeground=theme.ON_ACCENT, relief="flat", highlightthickness=1,
                                           highlightbackground=theme.PANEL_BORDER, font=theme.FONT, activestyle="none")
        self.received_listbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.received_listbox.bind("<Double-Button-1>", self._safe(lambda e: self._open_selected_received_file()))
        self.received_listbox.bind("<Return>", self._safe(lambda e: self._open_selected_received_file()))

        # earlier files (history is saved on disk) so the list isn't empty after a restart
        for e in self.server.history.list([KIND_FILE_FROM_PHONE])[-40:]:
            p = Path(e.get("path", ""))
            if p.exists():
                self._add_received_row(p, time.strftime("%H:%M:%S", time.localtime(e["ts"])))
        self.server.on_file_received(self._on_file_received_threadsafe)
        self._refresh_server_ui()

    # ---- server control ------------------------------------------------ #
    def _toggle_server(self):
        if self.server.is_running:
            self.server.stop()
        else:
            self._start_server()
        self._refresh_server_ui()

    def _start_server(self) -> bool:
        try:
            self.server.start()
            return True
        except OSError as exc:
            port = self.cfg.get("server_port")
            log.error("Could not start the server on port %s: %s", port, exc)
            messagebox.showerror(
                "Could not start the server",
                f"Port {port} is not available:\n{exc}\n\n"
                "Most likely another copy of this tool (or another program) is already using it.\n"
                "Close that one, or choose a different port in Settings.")
            return False

    def _refresh_server_ui(self):
        running = self.server.is_running
        port = self.cfg.get("server_port", 8765)
        if running:
            url = f"http://{net_utils.get_local_ip()}:{port}"
            self.lan_url_var.set(url)
            self.server_state_var.set(f"Running on port {port}")
            self.server_state_label.configure(style="Ok.TLabel")
            self.toggle_btn.configure(text="Stop Server")
            self._show_qr(url)
            self.qr_caption.configure(text="Scan with your phone camera (same Wi-Fi).")
        else:
            self.server_state_var.set("Stopped")
            self.server_state_label.configure(style="Heading.TLabel")
            self.toggle_btn.configure(text="Start Server")
            self.lan_url_var.set("")
            self.qr_label.configure(image="")
            self._qr_photo = None
            self.qr_caption.configure(text="Start the server, then scan the QR code with your phone camera.")

    def _show_qr(self, url: str):
        self._qr_photo = ImageTk.PhotoImage(make_qr_image(url, target_px=360))
        self.qr_label.configure(image=self._qr_photo)

    def _open_lan_url(self):
        if self.lan_url_var.get():
            import webbrowser
            webbrowser.open(self.lan_url_var.get())

    def _on_public_state(self, state: dict):
        """Called from the watcher thread; hop to the UI thread."""
        self.ui(lambda: self._apply_public_state(state))

    def _apply_public_state(self, state: dict):
        if state.get("url"):
            tag = "LIVE" if state.get("is_funnel") else "tailnet only"
            self.transfer_pub_var.set(f"{state['url']}   [{tag}]")
            self.transfer_pub_label.configure(style="Ok.TLabel" if state.get("is_funnel") else "Warn.TLabel")
        else:
            self.transfer_pub_var.set("not published yet - it will appear here by itself")
            self.transfer_pub_label.configure(style="Muted.TLabel")
        if hasattr(self, "_apply_public_page_state"):
            self._apply_public_page_state(state)

    # ---- laptop -> phone ---------------------------------------------- #
    @staticmethod
    def _unique_local_path(path: Path) -> Path:
        if not path.exists():
            return path
        i = 1
        while True:
            cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
            if not cand.exists():
                return cand
            i += 1

    def _add_files_to_share(self):
        paths = filedialog.askopenfilenames(title="Choose files to send to the phone")
        if not paths:
            return
        share = Path(self.cfg["share_folder"])
        share.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._copy_files_thread, args=(list(paths), share), name="CopyToShare", daemon=True).start()

    def _copy_files_thread(self, paths, share: Path):
        for i, src in enumerate(paths, 1):
            t0 = time.time()
            try:
                dest = self._unique_local_path(share / safe_filename(Path(src).name))
                shutil.copy2(src, dest)
                self.server.register_shared_file(dest)
                size = dest.stat().st_size
                log.info("Added to share folder: '%s' (%s, %.1fs)", dest.name, _fmt_size(size), time.time() - t0)
                self.ui(lambda n=dest.name, i=i, t=len(paths): self.share_status_var.set(f"Added {i}/{t}: {n}"))
            except OSError as exc:
                log.error("Could not copy '%s' to the share folder: %s", src, exc, exc_info=True)
                self.ui(lambda s=src, e=exc: messagebox.showerror("Copy failed", f"Could not copy:\n{s}\n\n{e}"))
        self.ui(lambda: self.share_status_var.set(f"Done - {len(paths)} file(s) ready for the phone"))

    def _add_folder_to_share(self):
        folder = filedialog.askdirectory(title="Choose a folder to send to the phone (it will be zipped)")
        if not folder:
            return
        src = Path(folder)
        share = Path(self.cfg["share_folder"])
        share.mkdir(parents=True, exist_ok=True)
        dest = self._unique_local_path(share / (safe_filename(src.name) + ".zip"))
        self.share_status_var.set(f"Zipping '{src.name}' ...")
        threading.Thread(target=self._zip_folder_thread, args=(src, dest), name="ZipFolder", daemon=True).start()

    def _zip_folder_thread(self, src: Path, dest: Path):
        try:
            n, _ = zip_utils.zip_folder(src, dest, progress_cb=lambda i, t: (i % 25 == 0 or i == t) and self.ui(
                lambda i=i, t=t: self.share_status_var.set(f"Zipping '{src.name}': {i}/{t} files")))
            self.server.register_shared_file(dest)
            self.ui(lambda: self.share_status_var.set(f"'{dest.name}' ready for the phone ({n} files)"))
        except Exception as exc:
            log.error("Zipping '%s' failed: %s", src, exc, exc_info=True)
            self.ui(lambda: messagebox.showerror("Zip failed", f"Could not zip the folder:\n{exc}"))

    # ---- folders ------------------------------------------------------- #
    def _open_folder(self, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)
        self._open_path(folder)

    def _open_share_folder(self):
        self._open_folder(self.cfg["share_folder"])

    def _open_received_folder(self):
        self._open_folder(self.cfg["download_folder"])

    def _open_path(self, path):
        """Open a file/folder with its default program. If Windows has NO default
        program for the type (e.g. a PDF with no reader), show the 'Open with'
        chooser instead of failing."""
        try:
            os.startfile(str(path))
        except OSError as exc:
            winerr = getattr(exc, "winerror", None)
            log.warning("No default program for '%s' (%s) - showing the 'Open with' dialog", path, exc)
            if winerr in (1155, 31, 2) or "application" in str(exc).lower():
                subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", str(path)])
            else:
                raise

    @staticmethod
    def _folder_summary(folder: Path) -> tuple:
        n = size = 0
        for p in folder.rglob("*"):
            if p.is_file():
                n += 1
                try:
                    size += p.stat().st_size
                except OSError:
                    pass
        return n, size

    @staticmethod
    def _clear_folder_contents(folder: Path) -> None:
        for child in folder.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError as exc:
                    log.warning("Could not delete %s: %s", child, exc)

    def _clear_received_files(self):
        folder = Path(self.cfg["download_folder"])
        n, size = self._folder_summary(folder) if folder.exists() else (0, 0)
        if not n:
            messagebox.showinfo("Nothing to clear", "The received-files folder is already empty.")
            return
        if messagebox.askyesno("Delete received files?",
                               f"This permanently deletes {n} file(s) ({_fmt_size(size)}) from:\n{folder}\n\nContinue?"):
            self._clear_folder_contents(folder)
            self.received_listbox.delete(0, "end")
            self._received_paths.clear()
            log.info("Cleared received folder: %d file(s), %s", n, _fmt_size(size))

    def _clear_share_folder(self):
        folder = Path(self.cfg["share_folder"])
        n, size = self._folder_summary(folder) if folder.exists() else (0, 0)
        if not n:
            messagebox.showinfo("Nothing to clear", "The share folder is already empty.")
            return
        if messagebox.askyesno("Delete shared files?",
                               f"This permanently deletes {n} file(s) ({_fmt_size(size)}) from:\n{folder}\n\nContinue?"):
            self._clear_folder_contents(folder)
            log.info("Cleared share folder: %d file(s), %s", n, _fmt_size(size))

    # ---- received list -------------------------------------------------- #
    def _add_received_row(self, path: Path, stamp: str = None):
        stamp = stamp or time.strftime("%H:%M:%S")
        try:
            size = _fmt_size(path.stat().st_size)
        except OSError:
            size = "?"
        self.received_listbox.insert(0, f"  {stamp}   {path.name}   ({size})")
        self._received_paths.insert(0, path)
        if self.received_listbox.size() > 200:
            self.received_listbox.delete("end")
            self._received_paths.pop()

    def _on_file_received_threadsafe(self, path: Path):
        self.ui(lambda: self._add_received_row(Path(path)))

    def _selected_received_path(self):
        sel = self.received_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select a file", "Click a file in the list first.")
            return None
        return self._received_paths[sel[0]]

    def _show_selected_received_file(self):
        p = self._selected_received_path()
        if p:
            subprocess.Popen(["explorer", f"/select,{p}"])

    def _open_selected_received_file(self, event=None):
        p = self._selected_received_path()
        if p:
            self._open_path(p)

    # ------------------------------------------------------------------ #
    # Text page
    # ------------------------------------------------------------------ #
    def _build_text_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        self._text_entries = []

        top = ttk.LabelFrame(tab, text="Text received from phone")
        top.pack(fill="both", expand=True, padx=12, pady=(10, 6))
        opts = ttk.Frame(top)
        opts.pack(fill="x", padx=8, pady=(8, 2))
        self.autocopy_var = tk.BooleanVar(value=self.cfg.get("auto_copy_text", True))
        ttk.Checkbutton(opts, text="Copy text from the phone to this laptop's clipboard automatically (local Wi-Fi only)",
                        variable=self.autocopy_var, command=self._safe(self._toggle_autocopy)).pack(side="left")

        self.text_listbox = tk.Listbox(top, height=6, bg=theme.PANEL, fg=theme.TEXT, selectbackground=theme.ACCENT,
                                       selectforeground=theme.ON_ACCENT, relief="flat", highlightthickness=1,
                                       highlightbackground=theme.PANEL_BORDER, font=theme.FONT, activestyle="none")
        self.text_listbox.pack(fill="x", padx=8, pady=6)
        self.text_listbox.bind("<<ListboxSelect>>", self._safe(lambda e: self._on_text_select()))

        self.text_preview = tk.Text(top, height=8, wrap="word", state="disabled")
        theme.style_log_widget(self.text_preview)
        self.text_preview.configure(font=("Segoe UI", 10))
        self.text_preview.pack(fill="both", expand=True, padx=8)
        add_context_menu(self.text_preview)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Button(row, text="Copy Selected", style="Accent.TButton", command=self._safe(self._copy_selected_text)).pack(side="left")
        ttk.Button(row, text="Save As...", command=self._safe(self._save_selected_text)).pack(side="left", padx=6)
        ttk.Button(row, text="Clear List", command=self._safe(self._clear_text_history)).pack(side="right")
        ttk.Label(top, text="Everything stays saved in the ReceivedText folder, even after you clear this list.",
                  style="Muted.TLabel").pack(anchor="w", padx=8, pady=(0, 8))

        send = ttk.LabelFrame(tab, text="Send text to phone  (Ctrl+Enter)")
        send.pack(fill="x", padx=12, pady=(6, 12))
        self.send_text_box = tk.Text(send, height=5, wrap="word")
        theme.style_log_widget(self.send_text_box)
        self.send_text_box.configure(font=("Segoe UI", 10), insertbackground=theme.TEXT)
        self.send_text_box.pack(fill="x", padx=8, pady=8)
        wire_field(self.send_text_box)
        self.send_text_box.bind("<Control-Return>", self._safe(lambda e: (self._send_text_to_phone(), "break")[1]))
        r = ttk.Frame(send)
        r.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(r, text="Send to Phone", style="Accent.TButton", command=self._safe(self._send_text_to_phone)).pack(side="left")
        self.send_text_status = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.send_text_status, style="Muted.TLabel").pack(side="left", padx=10)

        for entry in self.server.text_store.list_to_laptop()[-60:]:
            self._add_text_row(entry)
        self.server.text_store.on_new_to_laptop(self._on_text_received_threadsafe)

    def _toggle_autocopy(self):
        self.cfg["auto_copy_text"] = bool(self.autocopy_var.get())
        self.save_cfg(self.cfg)
        log.info("Auto-copy of phone text to the clipboard: %s", "ON" if self.cfg["auto_copy_text"] else "OFF")

    def _send_text_to_phone(self):
        text = self.send_text_box.get("1.0", "end-1c")
        if not text.strip():
            self.send_text_status.set("Type something first")
            return
        self.server.text_store.add_to_phone(text)
        log.info("Queued text for the phone (%d characters)", len(text))
        self.send_text_box.delete("1.0", "end")
        self.send_text_status.set(f"Sent {len(text)} characters - it appears on the phone page within seconds")

    def _add_text_row(self, entry: dict):
        stamp = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
        first = entry["text"].replace("\n", " ")[:70]
        mark = "  [copied]" if entry.get("copied") else ""
        self.text_listbox.insert(0, f"  {stamp}   {first}{mark}")
        self._text_entries.insert(0, entry)

    def _on_text_received_threadsafe(self, entry: dict):
        def add():
            self._add_text_row(entry)
            self.text_listbox.selection_clear(0, "end")
            self.text_listbox.selection_set(0)
            self._on_text_select()
        self.ui(add)

    def _on_text_select(self):
        sel = self.text_listbox.curselection()
        if not sel:
            return
        self.text_preview.configure(state="normal")
        self.text_preview.delete("1.0", "end")
        self.text_preview.insert("1.0", self._text_entries[sel[0]]["text"])
        self.text_preview.configure(state="disabled")

    def _selected_text(self):
        sel = self.text_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select a text", "Click an item in the list first.")
            return None
        return self._text_entries[sel[0]]["text"]

    def _copy_selected_text(self):
        t = self._selected_text()
        if t is not None:
            self.root.clipboard_clear()
            self.root.clipboard_append(t)
            self.send_text_status.set("Copied to the clipboard")

    def _save_selected_text(self):
        t = self._selected_text()
        if t is None:
            return
        path = filedialog.asksaveasfilename(title="Save text as", defaultextension=".txt",
                                            initialdir=self.cfg["text_folder"],
                                            filetypes=[("Text", "*.txt"), ("Python", "*.py"), ("Batch", "*.bat"), ("All files", "*.*")])
        if path:
            Path(path).write_text(t, encoding="utf-8")
            log.info("Saved a text to %s (%d characters)", path, len(t))

    def _clear_text_history(self):
        if messagebox.askyesno("Clear the list?", "This clears the list in this window.\n"
                                                  "The saved text files in ReceivedText stay on disk.\n\nContinue?"):
            n = self.server.text_store.clear()
            self.text_listbox.delete(0, "end")
            self._text_entries.clear()
            self.text_preview.configure(state="normal")
            self.text_preview.delete("1.0", "end")
            self.text_preview.configure(state="disabled")
            log.info("Text list cleared (%d item(s) hidden; data kept on disk)", n)

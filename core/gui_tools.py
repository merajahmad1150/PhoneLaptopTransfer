"""
core/gui_tools.py
ADB (wired transfer), Syncthing launcher and Settings pages.
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import adb_helper
import syncthing_helper
import theme
import ui_helpers
from config import BASE_DIR
from logger import get_logger

log = get_logger()
wire_field = ui_helpers.wire_field


class ToolsMixin:
    # ------------------------------------------------------------------ #
    # ADB
    # ------------------------------------------------------------------ #
    def _build_adb_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        ttk.Label(tab, wraplength=560, justify="left",
                  text="Optional: fast direct transfer over USB (or wireless ADB) for Android. "
                       "Needs Android platform-tools (adb) - set its path in Settings if it isn't on PATH."
                  ).pack(anchor="w", padx=12, pady=10)
        r = ttk.Frame(tab)
        r.pack(fill="x", padx=12)
        ttk.Button(r, text="Check ADB", command=self._safe(self._check_adb)).pack(side="left")
        ttk.Button(r, text="List devices", command=self._safe(self._list_adb_devices)).pack(side="left", padx=6)
        self.adb_status_var = tk.StringVar(value="Not checked yet")
        ttk.Label(r, textvariable=self.adb_status_var, style="Muted.TLabel", wraplength=380).pack(side="left", padx=10)

        push = ttk.LabelFrame(tab, text="Send file/folder to phone (push)")
        push.pack(fill="x", padx=12, pady=10)
        self.push_local_var = tk.StringVar()
        e = ttk.Entry(push, textvariable=self.push_local_var)
        e.pack(fill="x", padx=8, pady=(8, 2))
        wire_field(e)
        br = ttk.Frame(push)
        br.pack(fill="x", padx=8)
        ttk.Button(br, text="Choose file...", command=self._safe(self._browse_push_file)).pack(side="left")
        ttk.Button(br, text="Choose folder...", command=self._safe(self._browse_push_folder)).pack(side="left", padx=6)
        ttk.Label(push, text="Destination on phone:").pack(anchor="w", padx=8, pady=(6, 0))
        self.push_remote_var = tk.StringVar(value=adb_helper.COMMON_PHONE_PATHS[0])
        c = ttk.Combobox(push, textvariable=self.push_remote_var, values=adb_helper.COMMON_PHONE_PATHS)
        c.pack(fill="x", padx=8, pady=(0, 6))
        wire_field(c)
        ttk.Button(push, text="Push to phone", style="Accent.TButton", command=self._safe(self._do_push)).pack(anchor="e", padx=8, pady=(0, 8))

        pull = ttk.LabelFrame(tab, text="Get file/folder from phone (pull)")
        pull.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Label(pull, text="Source on phone:").pack(anchor="w", padx=8, pady=(8, 0))
        self.pull_remote_var = tk.StringVar(value=adb_helper.COMMON_PHONE_PATHS[0])
        c2 = ttk.Combobox(pull, textvariable=self.pull_remote_var, values=adb_helper.COMMON_PHONE_PATHS)
        c2.pack(fill="x", padx=8, pady=(0, 6))
        wire_field(c2)
        self.pull_local_var = tk.StringVar(value=self.cfg["download_folder"])
        e2 = ttk.Entry(pull, textvariable=self.pull_local_var)
        e2.pack(fill="x", padx=8, pady=(0, 2))
        wire_field(e2)
        ttk.Button(pull, text="Choose destination folder...", command=self._safe(self._browse_pull_local)).pack(anchor="w", padx=8)
        ttk.Button(pull, text="Pull from phone", style="Accent.TButton", command=self._safe(self._do_pull)).pack(anchor="e", padx=8, pady=8)

    def _check_adb(self):
        ok, msg = adb_helper.check_adb_available(self.cfg["adb_path"])
        self.adb_status_var.set(("OK: " if ok else "Not available: ") + msg)

    def _list_adb_devices(self):
        ok, devices, msg = adb_helper.list_devices(self.cfg["adb_path"])
        if not ok:
            self.adb_status_var.set("Error: " + msg)
        else:
            self.adb_status_var.set(f"{len(devices)} device(s): {', '.join(devices) or 'none'}" + (f"  |  {msg}" if msg else ""))

    def _browse_push_file(self):
        p = filedialog.askopenfilename(title="Choose a file to push")
        if p:
            self.push_local_var.set(p)

    def _browse_push_folder(self):
        p = filedialog.askdirectory(title="Choose a folder to push")
        if p:
            self.push_local_var.set(p)

    def _browse_pull_local(self):
        p = filedialog.askdirectory(title="Choose where to save pulled files")
        if p:
            self.pull_local_var.set(p)

    def _do_push(self):
        local, remote = self.push_local_var.get().strip(), self.push_remote_var.get().strip()
        if not local or not remote:
            messagebox.showwarning("Missing info", "Pick a local file/folder and a phone destination first.")
            return
        threading.Thread(target=self._push_thread, args=(local, remote), name="AdbPush", daemon=True).start()

    def _push_thread(self, local, remote):
        ok, out = adb_helper.push(self.cfg["adb_path"], local, remote)
        self.ui(lambda: self.adb_status_var.set("Push complete" if ok else f"Push failed: {out[:200]}"))

    def _do_pull(self):
        remote, local = self.pull_remote_var.get().strip(), self.pull_local_var.get().strip()
        if not local or not remote:
            messagebox.showwarning("Missing info", "Pick a phone source and a local destination first.")
            return
        threading.Thread(target=self._pull_thread, args=(remote, local), name="AdbPull", daemon=True).start()

    def _pull_thread(self, remote, local):
        ok, out = adb_helper.pull(self.cfg["adb_path"], remote, local)
        self.ui(lambda: self.adb_status_var.set("Pull complete" if ok else f"Pull failed: {out[:200]}"))

    # ------------------------------------------------------------------ #
    # Syncthing
    # ------------------------------------------------------------------ #
    def _build_sync_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        ttk.Label(tab, wraplength=560, justify="left",
                  text="Optional: Syncthing keeps chosen folders in sync between phone and laptop in the background. "
                       "This tool only launches it; pairing is done once in Syncthing's own web page."
                  ).pack(anchor="w", padx=12, pady=10)
        r = ttk.Frame(tab)
        r.pack(fill="x", padx=12, pady=6)
        ttk.Button(r, text="Check if installed", command=self._safe(self._check_syncthing)).pack(side="left")
        ttk.Button(r, text="Launch Syncthing", style="Accent.TButton", command=self._safe(self._launch_syncthing)).pack(side="left", padx=6)
        ttk.Button(r, text="Open web UI", command=self._safe(lambda: syncthing_helper.open_web_ui(self.cfg["syncthing_web_ui"]))).pack(side="left")
        self.sync_status_var = tk.StringVar(value="Not checked yet")
        ttk.Label(tab, textvariable=self.sync_status_var, style="Muted.TLabel").pack(anchor="w", padx=12, pady=(4, 10))
        ttk.Button(tab, text="Don't have Syncthing? Get it here", command=self._safe(syncthing_helper.open_download_page)).pack(anchor="w", padx=12)

    def _check_syncthing(self):
        ok = syncthing_helper.is_installed(self.cfg["syncthing_path"])
        self.sync_status_var.set("Installed" if ok else "Not found (set its path in Settings)")

    def _launch_syncthing(self):
        ok, msg = syncthing_helper.launch_if_not_running(self.cfg["syncthing_path"])
        self.sync_status_var.set(msg)

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #
    def _build_settings_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        self.set_vars = {}
        fields = [
            ("server_port", "Server port", "int", None),
            ("download_folder", "Received files folder (phone -> laptop)", "str", "dir"),
            ("share_folder", "Share folder (laptop -> phone)", "str", "dir"),
            ("text_folder", "Saved texts folder", "str", "dir"),
            ("frontend_visible_hours", "Hide items from the phone page after (hours, 0 = never)", "float", None),
            ("adb_path", "ADB path", "str", "file"),
            ("scrcpy_path", "scrcpy path", "str", "file"),
            ("uxplay_path", "UxPlay path (iPhone AirPlay, optional)", "str", "file"),
            ("syncthing_path", "Syncthing path", "str", "file"),
            ("tailscale_exe", "tailscale.exe (blank = find automatically)", "str", "file"),
            ("tailscale_publisher_path", "Tailscale publisher script", "str", "file"),
            ("parallel_uploads", "Files the phone uploads at once", "int", None),
            ("min_free_space_mb", "Refuse uploads below this free space (MB)", "int", None),
        ]
        g = ttk.Frame(tab)
        g.pack(fill="x", padx=12, pady=10)
        g.columnconfigure(1, weight=1)
        for i, (key, label, kind, browse) in enumerate(fields):
            ttk.Label(g, text=label).grid(row=i, column=0, sticky="w", padx=(0, 10), pady=4)
            v = tk.StringVar(value=str(self.cfg.get(key, "")))
            self.set_vars[key] = (v, kind)
            en = ttk.Entry(g, textvariable=v, width=48)
            en.grid(row=i, column=1, sticky="ew", pady=4)
            wire_field(en)
            if browse:
                ttk.Button(g, text="Browse...", command=self._safe(lambda var=v, b=browse: self._browse_setting(var, b))).grid(
                    row=i, column=2, padx=(6, 0))

        o = ttk.LabelFrame(tab, text="Behaviour")
        o.pack(fill="x", padx=12, pady=6)
        self.set_bools = {}
        for key, label in [("auto_start_server", "Start the server automatically when the tool opens"),
                           ("auto_copy_text", "Copy text from the phone (local Wi-Fi) to the clipboard automatically"),
                           ("right_click_pastes", "Right-click pastes immediately (hold Shift for the full menu)")]:
            v = tk.BooleanVar(value=bool(self.cfg.get(key, True)))
            self.set_bools[key] = v
            ttk.Checkbutton(o, text=label, variable=v).pack(anchor="w", padx=8, pady=3)
        mr = ttk.Frame(o)
        mr.pack(fill="x", padx=8, pady=(4, 8))
        ttk.Label(mr, text="Start-up mode:").pack(side="left")
        self.startup_mode_var = tk.StringVar(value=self.cfg.get("startup_mode", "ask"))
        ttk.Combobox(mr, textvariable=self.startup_mode_var, values=["ask", "gui", "web"], state="readonly", width=8).pack(side="left", padx=8)
        ttk.Label(mr, text="ask = show the choice every time,  gui = desktop window,  web = control panel in a browser",
                  style="Muted.TLabel").pack(side="left")

        b = ttk.Frame(tab)
        b.pack(fill="x", padx=12, pady=10)
        ttk.Button(b, text="Save settings", style="Accent.TButton", command=self._safe(self._save_settings)).pack(side="left")
        ttk.Button(b, text="Keyboard shortcuts (F1)", command=self._safe(self._show_shortcuts)).pack(side="left", padx=8)
        ttk.Label(tab, style="Muted.TLabel", wraplength=560, justify="left",
                  text=f"Everything (config, logs, data, temp, default folders) lives inside:  {BASE_DIR}\n"
                       "Changing the port or folders takes effect the next time the server starts."
                  ).pack(anchor="w", padx=12, pady=(0, 12))

    def _browse_setting(self, var, kind):
        p = filedialog.askdirectory(title="Choose folder") if kind == "dir" else filedialog.askopenfilename(title="Choose file")
        if p:
            var.set(p)

    def _save_settings(self):
        new = {}
        for key, (var, kind) in self.set_vars.items():
            raw = var.get().strip()
            try:
                if kind == "int":
                    new[key] = int(raw)
                elif kind == "float":
                    new[key] = float(raw)
                else:
                    new[key] = raw
            except ValueError:
                messagebox.showerror("Invalid value", f"'{key}' must be a number.")
                return
        if not (1 <= new["server_port"] <= 65535):
            messagebox.showerror("Invalid port", "Port must be between 1 and 65535.")
            return
        for key in ("adb_path", "scrcpy_path", "syncthing_path"):
            if not new.get(key):
                new[key] = key.split("_")[0]
        if not new.get("tailscale_publisher_path"):
            new["tailscale_publisher_path"] = self.cfg["tailscale_publisher_path"]
        port_changed = new["server_port"] != self.cfg.get("server_port")
        self.cfg.update(new)
        for key, var in self.set_bools.items():
            self.cfg[key] = bool(var.get())
        self.cfg["startup_mode"] = self.startup_mode_var.get()
        ui_helpers.set_right_click_pastes(self.cfg["right_click_pastes"])
        for k in ("download_folder", "share_folder", "text_folder"):
            Path(self.cfg[k]).mkdir(parents=True, exist_ok=True)
        self.save_cfg(self.cfg)
        from config import redacted
        log.info("Settings saved: %s", redacted(self.cfg))
        self.autocopy_var.set(self.cfg["auto_copy_text"])
        self.server.public.refresh_now()
        messagebox.showinfo("Saved", "Settings saved." + ("\nRestart the server for the new port to apply." if port_changed and self.server.is_running else ""))

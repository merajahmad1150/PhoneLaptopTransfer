"""
core/gui_network.py
"Public Access" and "Shared Rooms" pages.

Public Access is AUTOMATIC now: publish the local port with Tailscale however you
like (your PUBLISH-TOOL.bat, or a command) and this page shows the live public
link and its QR code by itself. Nothing to paste, no "Show QR" button.
"""

import os
import secrets
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import ImageTk

import net_utils
import room_manager
import theme
import ui_helpers
from logger import get_logger
from qr_helper import make_qr_image

log = get_logger()
wire_field = ui_helpers.wire_field
add_context_menu = ui_helpers.add_context_menu


class NetworkMixin:
    def _copy_text_var(self, var: tk.StringVar):
        value = var.get()
        if value:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)

    # ------------------------------------------------------------------ #
    # Public Access
    # ------------------------------------------------------------------ #
    def _build_public_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        self._public_photo = None

        live = ttk.LabelFrame(tab, text="Public link  (found automatically)")
        live.pack(fill="x", padx=12, pady=(10, 6))
        self.public_status_var = tk.StringVar(value="Looking for your Tailscale publisher ...")
        self.public_status_label = ttk.Label(live, textvariable=self.public_status_var, style="Heading.TLabel",
                                             wraplength=560, justify="left")
        self.public_status_label.pack(anchor="w", padx=8, pady=(8, 4))
        row = ttk.Frame(live)
        row.pack(fill="x", padx=8, pady=4)
        self.public_url_var = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.public_url_var, state="readonly")
        e.pack(side="left", fill="x", expand=True)
        add_context_menu(e)
        ttk.Button(row, text="Copy", command=self._safe(lambda: self._copy_text_var(self.public_url_var))).pack(side="left", padx=6)
        ttk.Button(row, text="Open", command=self._safe(self._open_public_url)).pack(side="left")
        self.public_qr_label = tk.Label(live, bg=theme.PANEL, bd=0)
        self.public_qr_label.pack(pady=8)

        how = ttk.LabelFrame(tab, text="How to make it live")
        how.pack(fill="x", padx=12, pady=6)
        port = self.cfg.get("server_port", 8765)
        ttk.Label(how, justify="left", wraplength=560,
                  text=f"1.  Start the server (Wi-Fi Transfer page).\n"
                       f"2.  Publish local port {port} with your Tailscale script (or: tailscale funnel --https=8443 {port}).\n"
                       f"3.  That's it - this page and the QR code update by themselves within a few seconds.").pack(anchor="w", padx=8, pady=8)
        r = ttk.Frame(how)
        r.pack(fill="x", padx=8, pady=(0, 8))
        self.port_text_var = tk.StringVar(value=str(port))
        ttk.Label(r, text="Port to publish:").pack(side="left")
        pe = ttk.Entry(r, textvariable=self.port_text_var, state="readonly", width=8)
        pe.pack(side="left", padx=6)
        ttk.Button(r, text="Copy port", command=self._safe(lambda: self._copy_text_var(self.port_text_var))).pack(side="left")
        ttk.Button(r, text="Run publisher script", style="Accent.TButton",
                   command=self._safe(self._open_publisher_tool)).pack(side="left", padx=12)
        ttk.Button(r, text="Check now", command=self._safe(lambda: self.server.public.refresh_now())).pack(side="left")

        pin = ttk.LabelFrame(tab, text="Access PIN (recommended when public)")
        pin.pack(fill="x", padx=12, pady=6)
        self.require_pin_var = tk.BooleanVar(value=self.cfg.get("require_access_pin", False))
        ttk.Checkbutton(pin, text="Ask visitors for a PIN", variable=self.require_pin_var,
                        command=self._safe(self._toggle_require_pin)).pack(anchor="w", padx=8, pady=(8, 2))
        pr = ttk.Frame(pin)
        pr.pack(fill="x", padx=8, pady=(0, 8))
        self.pin_var = tk.StringVar(value=self.cfg.get("access_pin", ""))
        pe2 = ttk.Entry(pr, textvariable=self.pin_var, state="readonly", width=12, font=("Consolas", 12, "bold"))
        pe2.pack(side="left")
        add_context_menu(pe2)
        ttk.Button(pr, text="Copy", command=self._safe(lambda: self._copy_text_var(self.pin_var))).pack(side="left", padx=6)
        ttk.Button(pr, text="New PIN", command=self._safe(self._generate_new_pin)).pack(side="left")
        ttk.Label(pin, text="After 5 wrong tries a visitor is locked out for a while. The PIN is never written to the log.",
                  style="Muted.TLabel").pack(anchor="w", padx=8, pady=(0, 8))

        adv = ttk.LabelFrame(tab, text="Advanced")
        adv.pack(fill="x", padx=12, pady=(6, 12))
        self.auto_detect_var = tk.BooleanVar(value=self.cfg.get("auto_detect_public_url", True))
        ttk.Checkbutton(adv, text="Detect the public link automatically from Tailscale", variable=self.auto_detect_var,
                        command=self._safe(self._save_public_advanced)).pack(anchor="w", padx=8, pady=(8, 2))
        ar = ttk.Frame(adv)
        ar.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Label(ar, text="Fallback link (only used if nothing is detected):").pack(side="left")
        self.manual_url_var = tk.StringVar(value=self.cfg.get("public_url_manual", ""))
        me = ttk.Entry(ar, textvariable=self.manual_url_var, width=36)
        me.pack(side="left", padx=6)
        wire_field(me)
        me.bind("<Return>", self._safe(lambda ev: (self._save_public_advanced(), "break")[1]))
        ttk.Button(ar, text="Save", command=self._safe(self._save_public_advanced)).pack(side="left")

        self.server.public.on_change(self._on_public_state)
        self._apply_public_state(self.server.public.state)

    def _apply_public_page_state(self, state: dict):
        self.public_status_var.set(state.get("message", ""))
        url = state.get("url", "")
        self.public_url_var.set(url)
        self.public_status_label.configure(style="Ok.TLabel" if state.get("is_funnel") and url else "Heading.TLabel")
        if url:
            self._public_photo = ImageTk.PhotoImage(make_qr_image(url, target_px=360))
            self.public_qr_label.configure(image=self._public_photo)
        else:
            self.public_qr_label.configure(image="")
            self._public_photo = None
        self.server.public.cfg = self.cfg
        if hasattr(self, "_refresh_room_links"):
            self._refresh_room_links()

    def _open_public_url(self):
        if self.public_url_var.get():
            webbrowser.open(self.public_url_var.get())

    def _open_publisher_tool(self):
        path = self.cfg.get("tailscale_publisher_path", "")
        if not path or not Path(path).exists():
            messagebox.showerror("Publisher script not found",
                                 f"I couldn't find:\n{path}\n\nSet the correct path in Settings. "
                                 "(Or publish the port yourself with Tailscale - this page finds it automatically.)")
            return
        log.info("Opening publisher script: %s", path)
        os.startfile(path, cwd=str(Path(path).parent))

    def _save_public_advanced(self):
        self.cfg["auto_detect_public_url"] = bool(self.auto_detect_var.get())
        self.cfg["public_url_manual"] = self.manual_url_var.get().strip()
        self.save_cfg(self.cfg)
        self.server.public.refresh_now()

    def _toggle_require_pin(self):
        want = bool(self.require_pin_var.get())
        if want and not self.cfg.get("access_pin"):
            self._generate_new_pin(save=False)
        self.cfg["require_access_pin"] = want
        self.save_cfg(self.cfg)
        log.info("Access PIN requirement: %s", "ON" if want else "OFF")

    def _generate_new_pin(self, save: bool = True):
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        self.cfg["access_pin"] = pin
        self.pin_var.set(pin)
        if save:
            self.save_cfg(self.cfg)
        log.info("A new access PIN was generated (not shown in the log)")

    # ------------------------------------------------------------------ #
    # Shared Rooms
    # ------------------------------------------------------------------ #
    def _build_rooms_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        ttk.Label(tab, wraplength=560, justify="left",
                  text="Let someone else pair THEIR OWN laptop and phone through this tool, without touching your files. "
                       "Each visitor gets an isolated room (own files, own text) that expires automatically. "
                       "Off by default - turning it on lets anyone with the link use your storage and bandwidth temporarily."
                  ).pack(anchor="w", padx=12, pady=10)
        self.rooms_enabled_var = tk.BooleanVar(value=self.cfg.get("rooms_enabled", False))
        ttk.Checkbutton(tab, text="Enable Shared Rooms", variable=self.rooms_enabled_var,
                        command=self._safe(self._toggle_rooms_enabled)).pack(anchor="w", padx=12)

        lim = ttk.LabelFrame(tab, text="Safety limits")
        lim.pack(fill="x", padx=12, pady=10)
        g = ttk.Frame(lim)
        g.pack(fill="x", padx=8, pady=8)
        self.room_vars = {}
        for i, (key, label, default) in enumerate([("room_max_age_hours", "Delete a room after (hours)", 24),
                                                   ("room_max_file_mb", "Max file (MB)", 500),
                                                   ("room_max_total_mb", "Max per room (MB)", 2048),
                                                   ("room_max_rooms", "Max rooms", 20)]):
            ttk.Label(g, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 6), pady=3)
            v = tk.StringVar(value=str(self.cfg.get(key, default)))
            self.room_vars[key] = v
            en = ttk.Entry(g, textvariable=v, width=9)
            en.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 18))
            wire_field(en)
        ttk.Button(lim, text="Save limits", style="Accent.TButton", command=self._safe(self._save_room_limits)).pack(anchor="w", padx=8, pady=(0, 8))

        links = ttk.LabelFrame(tab, text="Link to share with someone")
        links.pack(fill="x", padx=12, pady=(0, 10))
        self.rooms_lan_link_var = tk.StringVar()
        self.rooms_public_link_var = tk.StringVar()
        for label, var in (("Same Wi-Fi:", self.rooms_lan_link_var), ("From anywhere (public link):", self.rooms_public_link_var)):
            ttk.Label(links, text=label).pack(anchor="w", padx=8, pady=(6, 0))
            rr = ttk.Frame(links)
            rr.pack(fill="x", padx=8, pady=(0, 4))
            en = ttk.Entry(rr, textvariable=var, state="readonly")
            en.pack(side="left", fill="x", expand=True)
            add_context_menu(en)
            ttk.Button(rr, text="Copy", command=self._safe(lambda v=var: self._copy_text_var(v))).pack(side="left", padx=(6, 0))

        act = ttk.LabelFrame(tab, text="Active rooms")
        act.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        br = ttk.Frame(act)
        br.pack(fill="x", padx=8, pady=8)
        ttk.Button(br, text="Refresh", command=self._safe(self._refresh_active_rooms)).pack(side="left")
        ttk.Button(br, text="Delete selected", command=self._safe(self._delete_selected_room)).pack(side="left", padx=6)
        ttk.Button(br, text="Delete all", style="Danger.TButton", command=self._safe(self._delete_all_rooms)).pack(side="left")
        self.rooms_listbox = tk.Listbox(act, height=6, bg=theme.PANEL, fg=theme.TEXT, selectbackground=theme.ACCENT,
                                        selectforeground=theme.ON_ACCENT, relief="flat", highlightthickness=1,
                                        highlightbackground=theme.PANEL_BORDER, font=theme.FONT_MONO, activestyle="none")
        self.rooms_listbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._refresh_room_links()
        self._refresh_active_rooms()

    def _toggle_rooms_enabled(self):
        self.cfg["rooms_enabled"] = bool(self.rooms_enabled_var.get())
        self.save_cfg(self.cfg)
        log.info("Shared Rooms %s", "ENABLED" if self.cfg["rooms_enabled"] else "disabled")

    def _save_room_limits(self):
        try:
            for key, var in self.room_vars.items():
                self.cfg[key] = float(var.get().strip()) if key != "room_max_rooms" else int(var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid value", "Every limit must be a number.")
            return
        self.save_cfg(self.cfg)
        log.info("Room limits saved: %s", {k: self.cfg[k] for k in self.room_vars})

    def _refresh_room_links(self):
        if not hasattr(self, "rooms_lan_link_var"):
            return
        port = self.cfg.get("server_port", 8765)
        self.rooms_lan_link_var.set(f"http://{net_utils.get_local_ip()}:{port}/room")
        pub = self.server.public.state.get("url", "")
        self.rooms_public_link_var.set(pub.rstrip("/") + "/room" if pub else "(appears by itself once you publish the port)")

    def _refresh_active_rooms(self):
        self.rooms_listbox.delete(0, "end")
        rooms = room_manager.list_active_rooms()
        if not rooms:
            self.rooms_listbox.insert("end", "  No active rooms")
            return
        for r in rooms:
            age = int((time.time() - r["last_activity"]) / 60)
            self.rooms_listbox.insert("end", f"  {r['code']}   {r['file_count']} file(s)   {r['size_mb']:.1f} MB   last active {age} min ago")

    def _delete_selected_room(self):
        sel = self.rooms_listbox.curselection()
        if not sel:
            messagebox.showwarning("Nothing selected", "Select a room first.")
            return
        line = self.rooms_listbox.get(sel[0]).strip()
        if line and not line.startswith("No active"):
            room_manager.delete_room(line.split()[0])
            self._refresh_active_rooms()

    def _delete_all_rooms(self):
        n = room_manager.delete_all_rooms()
        log.info("Deleted all %d active room(s) from the GUI", n)
        self._refresh_active_rooms()

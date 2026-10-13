"""
core/gui_mirror.py
Screen Mirror page.

  Android, USB            adb + scrcpy (mouse control, drag-drop files, clipboard sync)
  Android, QR (wireless)  Android 11+ "Wireless debugging > Pair device with QR code":
                          the laptop shows the QR, you scan it, tap Allow, the phone is
                          paired and scrcpy opens by itself (same Wi-Fi)
  Android, other network  connect by address (e.g. the phone's Tailscale IP:port)
  iPhone / iPad           AirPlay: Control Center > Screen Mirroring > pick this laptop
                          (needs the optional UxPlay receiver; same Wi-Fi)

Honest limit: a web page cannot capture a phone's screen (iOS Safari and Android
browsers don't offer screen capture), so there is no "scan a link and share from
the browser" mode. See README for details.
"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import ImageTk

import adb_helper
import scrcpy_helper
import theme
import ui_helpers
from logger import get_logger
from qr_helper import make_qr_image

log = get_logger()
wire_field = ui_helpers.wire_field


class MirrorMixin:
    def _build_mirror_page(self, page):
        tab = ui_helpers.make_scrollable(page)
        self._pair_photo = None
        self._pair_cancel = None

        ttk.Label(tab, text="See your phone on this screen and control it with the mouse.",
                  style="Heading.TLabel").pack(anchor="w", padx=12, pady=(10, 2))
        ttk.Label(tab, text="Android: USB or wireless QR.   iPhone/iPad: AirPlay.   (Browsers cannot capture a phone's screen - "
                            "see 'Why no link-only mode?' below.)", style="Muted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        # ---- devices ----
        dev = ttk.LabelFrame(tab, text="1. Android phone (USB cable or already paired)")
        dev.pack(fill="x", padx=12, pady=6)
        r = ttk.Frame(dev)
        r.pack(fill="x", padx=8, pady=8)
        ttk.Button(r, text="Refresh devices  (F5)", command=self._safe(self._refresh_mirror_devices)).pack(side="left")
        self.mirror_device_var = tk.StringVar()
        self.mirror_device_combo = ttk.Combobox(r, textvariable=self.mirror_device_var, state="readonly", width=34)
        self.mirror_device_combo.pack(side="left", padx=8)
        ttk.Button(r, text="Start Mirroring", style="Accent.TButton", command=self._safe(self._start_mirroring)).pack(side="left")
        self.mirror_status_var = tk.StringVar(value="Plug the phone in with USB debugging ON, then press Refresh devices.")
        ttk.Label(dev, textvariable=self.mirror_status_var, style="Muted.TLabel", wraplength=560, justify="left").pack(
            anchor="w", padx=8, pady=(0, 8))

        # ---- QR pairing ----
        qr = ttk.LabelFrame(tab, text="2. Android wireless - scan a QR code (Android 11+, same Wi-Fi)")
        qr.pack(fill="x", padx=12, pady=6)
        ttk.Label(qr, justify="left", wraplength=560,
                  text="On the phone:  Settings > Developer options > Wireless debugging (turn ON) > 'Pair device with QR code'.\n"
                       "Then press the button below and scan the QR code that appears. Tap Allow if the phone asks.").pack(
            anchor="w", padx=8, pady=(8, 4))
        r2 = ttk.Frame(qr)
        r2.pack(fill="x", padx=8, pady=4)
        ttk.Button(r2, text="Show pairing QR code", style="Accent.TButton", command=self._safe(self._start_qr_pairing)).pack(side="left")
        ttk.Button(r2, text="Cancel", command=self._safe(self._cancel_qr_pairing)).pack(side="left", padx=6)
        self.pair_qr_label = tk.Label(qr, bg=theme.PANEL, bd=0)
        self.pair_qr_label.pack(pady=6)
        self.pair_status_var = tk.StringVar(value="")
        ttk.Label(qr, textvariable=self.pair_status_var, style="Warn.TLabel", wraplength=560, justify="left").pack(
            anchor="w", padx=8, pady=(0, 8))

        # ---- connect by address ----
        net = ttk.LabelFrame(tab, text="3. Android on a different network (connect by address)")
        net.pack(fill="x", padx=12, pady=6)
        ttk.Label(net, justify="left", wraplength=560,
                  text="If the phone and laptop are both on Tailscale (or any reachable address), enter the phone's\n"
                       "address as  ip:port  (the port shown on the phone's Wireless debugging screen).").pack(anchor="w", padx=8, pady=(8, 4))
        r3 = ttk.Frame(net)
        r3.pack(fill="x", padx=8, pady=(0, 8))
        self.connect_addr_var = tk.StringVar()
        e = ttk.Entry(r3, textvariable=self.connect_addr_var, width=30)
        e.pack(side="left")
        wire_field(e)
        e.bind("<Return>", self._safe(lambda ev: (self._connect_by_address(), "break")[1]))
        ttk.Button(r3, text="Connect", command=self._safe(self._connect_by_address)).pack(side="left", padx=8)

        # ---- iPhone ----
        ios = ttk.LabelFrame(tab, text="4. iPhone / iPad (AirPlay, same Wi-Fi)")
        ios.pack(fill="x", padx=12, pady=6)
        ttk.Label(ios, justify="left", wraplength=560,
                  text="Start the AirPlay receiver here, then on the iPhone open Control Center > Screen Mirroring and pick\n"
                       "'Laptop (PLT)'. Needs the free UxPlay program (set its path in Settings > uxplay_path).").pack(anchor="w", padx=8, pady=(8, 4))
        r4 = ttk.Frame(ios)
        r4.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(r4, text="Start AirPlay receiver", style="Accent.TButton", command=self._safe(self._start_airplay)).pack(side="left")
        self.ios_status_var = tk.StringVar(value="")
        ttk.Label(r4, textvariable=self.ios_status_var, style="Muted.TLabel").pack(side="left", padx=10)

        # ---- quality ----
        q = ttk.LabelFrame(tab, text="Mirror quality (Android)")
        q.pack(fill="x", padx=12, pady=6)
        g = ttk.Frame(q)
        g.pack(fill="x", padx=8, pady=8)
        self.mirror_vars = {}
        for i, (key, label) in enumerate([("scrcpy_max_size", "Max size (px)"), ("scrcpy_bitrate_mbps", "Bitrate (Mbps)"),
                                          ("scrcpy_max_fps", "Max FPS")]):
            ttk.Label(g, text=label).grid(row=0, column=i * 2, sticky="w", padx=(0, 4))
            v = tk.StringVar(value=str(self.cfg.get(key, "")))
            self.mirror_vars[key] = v
            en = ttk.Entry(g, textvariable=v, width=7)
            en.grid(row=0, column=i * 2 + 1, padx=(0, 14))
            wire_field(en)
        self.screen_off_var = tk.BooleanVar(value=self.cfg.get("scrcpy_turn_screen_off", False))
        ttk.Checkbutton(g, text="Turn phone screen off", variable=self.screen_off_var).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(g, text="Save quality", command=self._safe(self._save_mirror_settings)).grid(row=1, column=4, columnspan=2, sticky="e", pady=(6, 0))

        why = ttk.LabelFrame(tab, text="Why no 'scan a link and share from the browser' mode?")
        why.pack(fill="x", padx=12, pady=(6, 12))
        ttk.Label(why, justify="left", wraplength=560, style="Muted.TLabel",
                  text="iPhone Safari and Android browsers do not allow a web page to capture the phone's screen (only desktop "
                       "browsers can). Capturing a phone screen needs either ADB/scrcpy (Android), AirPlay (iPhone), or a small "
                       "app installed on the phone. Over the internet this additionally needs a relay server. "
                       "See README > Screen mirroring for what is possible.").pack(anchor="w", padx=8, pady=8)

    # ---- helpers ----
    def _refresh_mirror_devices(self):
        ok, devices, msg = adb_helper.list_devices(self.cfg["adb_path"])
        if not ok:
            self.mirror_status_var.set("Problem: " + msg)
            return
        self.mirror_device_combo.configure(values=devices)
        if devices:
            if self.mirror_device_var.get() not in devices:
                self.mirror_device_var.set(devices[0])
            self.mirror_status_var.set(f"{len(devices)} phone(s) ready." + (f"  Note: {msg}" if msg else ""))
        else:
            self.mirror_device_var.set("")
            self.mirror_status_var.set("No phone ready. " + (msg or "Plug it in with USB debugging ON, or use the QR option below."))

    def _save_mirror_settings(self):
        try:
            for key, var in self.mirror_vars.items():
                self.cfg[key] = int(var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid value", "Size, bitrate and FPS must be whole numbers.")
            return
        self.cfg["scrcpy_turn_screen_off"] = bool(self.screen_off_var.get())
        self.save_cfg(self.cfg)
        self.mirror_status_var.set("Quality saved - applies the next time you start mirroring.")

    def _start_mirroring(self, serial: str = None):
        serial = serial or self.mirror_device_var.get() or None
        if not serial:
            ok, devices, msg = adb_helper.list_devices(self.cfg["adb_path"])
            if ok and devices:
                serial = devices[0]
            else:
                messagebox.showwarning("No phone found", (msg or "No Android phone is connected.") +
                                       "\n\nPlug it in with USB debugging ON, or pair it with the QR code below.")
                return
        self.mirror_status_var.set("Starting scrcpy ...")
        threading.Thread(target=self._mirror_thread, args=(serial,), name="Scrcpy", daemon=True).start()

    def _mirror_thread(self, serial):
        ok, msg = scrcpy_helper.launch(self.cfg["scrcpy_path"], self.cfg, serial)
        self.ui(lambda: self.mirror_status_var.set(msg))

    # ---- QR pairing ----
    def _start_qr_pairing(self):
        adb = self.cfg["adb_path"]
        ok, msg = adb_helper.check_adb_available(adb)
        if not ok:
            messagebox.showerror("ADB not available", msg)
            return
        self._cancel_qr_pairing()
        name, pw = adb_helper.new_pairing_credentials()
        self._pair_photo = ImageTk.PhotoImage(make_qr_image(adb_helper.pairing_qr_text(name, pw), target_px=340))
        self.pair_qr_label.configure(image=self._pair_photo)
        self.pair_status_var.set("Scan this on the phone: Wireless debugging > Pair device with QR code ...")
        cancel = threading.Event()
        self._pair_cancel = cancel
        threading.Thread(target=self._pair_worker, args=(adb, name, pw, cancel), name="QrPairing", daemon=True).start()

    def _pair_worker(self, adb, name, pw, cancel):
        ok, msg, serial = adb_helper.pair_with_qr(
            adb, name, pw, status_cb=lambda m: self.ui(lambda: self.pair_status_var.set(m)), cancel=cancel)
        self.ui(lambda: self._pair_done(ok, msg, serial))

    def _pair_done(self, ok, msg, serial):
        self.pair_status_var.set(msg)
        if ok:
            self.pair_qr_label.configure(image="")
            self._pair_photo = None
            self._refresh_mirror_devices()
            if serial:
                self.mirror_device_var.set(serial)
                self._start_mirroring(serial)

    def _cancel_qr_pairing(self):
        if self._pair_cancel is not None:
            self._pair_cancel.set()
            self._pair_cancel = None
        self.pair_qr_label.configure(image="")
        self._pair_photo = None

    def _connect_by_address(self):
        addr = self.connect_addr_var.get().strip()
        ok, msg = adb_helper.connect_address(self.cfg["adb_path"], addr)
        self.mirror_status_var.set(msg)
        if ok:
            self._refresh_mirror_devices()
            self.mirror_device_var.set(addr)
            self._start_mirroring(addr)
        else:
            messagebox.showwarning("Could not connect", msg)

    def _start_airplay(self):
        self.ios_status_var.set("Starting ...")
        threading.Thread(target=self._airplay_thread, name="AirPlay", daemon=True).start()

    def _airplay_thread(self):
        ok, msg = scrcpy_helper.launch_airplay(self.cfg.get("uxplay_path", ""))
        self.ui(lambda: self.ios_status_var.set(msg))

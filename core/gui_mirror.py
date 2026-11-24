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

import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

import adb_helper
import scrcpy_helper
import theme
import ui_helpers
from logger import get_logger
from history_store import KIND_FILE_ADB
from qr_helper import make_qr_image

log = get_logger()
wire_field = ui_helpers.wire_field

# (label, max size px (0 = native), Mbps, fps)
QUALITY_PRESETS = {
    "Maximum - native resolution, 40 Mbps, 60 fps": (0, 40, 60),
    "High - 1920 px, 24 Mbps, 60 fps": (1920, 24, 60),
    "Balanced - 1280 px, 12 Mbps, 30 fps": (1280, 12, 30),
    "Low bandwidth - 800 px, 4 Mbps, 30 fps": (800, 4, 30),
}
_PUSHED = re.compile(r"^(.+): \d+ files? pushed")


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
        self.mirror_status_var = ui_helpers.StampedVar(value="Plug the phone in with USB debugging ON, then press Refresh devices.")
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
        self.pair_status_var = ui_helpers.StampedVar(value="")
        ttk.Label(qr, textvariable=self.pair_status_var, style="Warn.TLabel", wraplength=560, justify="left").pack(
            anchor="w", padx=8, pady=(0, 4))
        ttk.Separator(qr).pack(fill="x", padx=8, pady=4)
        ttk.Label(qr, justify="left", wraplength=560,
                  text="Pair with a code (works even when the QR is not detected): on the phone choose 'Pair device with pairing code'. "
                       "It shows an address like 192.168.1.5:37199 and a 6-digit code. Type them here:").pack(anchor="w", padx=8)
        rc = ttk.Frame(qr)
        rc.pack(fill="x", padx=8, pady=(4, 8))
        self.pair_addr_var, self.pair_code_var = tk.StringVar(), tk.StringVar()
        ea = ttk.Entry(rc, textvariable=self.pair_addr_var, width=24)
        ea.pack(side="left")
        wire_field(ea)
        ec = ttk.Entry(rc, textvariable=self.pair_code_var, width=9)
        ec.pack(side="left", padx=6)
        wire_field(ec)
        ec.bind("<Return>", self._safe(lambda ev: (self._pair_by_code(), "break")[1]))
        ttk.Button(rc, text="Pair", command=self._safe(self._pair_by_code)).pack(side="left", padx=4)

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
        self.ios_status_var = ui_helpers.StampedVar(value="")
        ttk.Label(r4, textvariable=self.ios_status_var, style="Muted.TLabel").pack(side="left", padx=10)

        # ---- files & clipboard while mirroring ----
        fx = ttk.LabelFrame(tab, text="5. Send files from this laptop to the phone  (photos/videos land in the phone gallery)")
        fx.pack(fill="x", padx=12, pady=6)
        ttk.Label(fx, justify="left", wraplength=560,
                  text="Instagram, WhatsApp and the Gallery only list what is on the PHONE. Use this to copy videos/photos/documents from the "
                       "laptop into the phone's gallery folder (DCIM/PLT) - then pick them normally in Instagram's + button.\n"
                       "You can also just DRAG files onto the mirror window: they go to the same gallery folder.").pack(anchor="w", padx=8, pady=(8, 4))
        r5 = ttk.Frame(fx)
        r5.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Button(r5, text="Choose photos / videos / files ...  (Ctrl+G)", style="Accent.TButton",
                   command=self._safe(self._send_files_to_phone_gallery)).pack(side="left")
        self.gallery_status_var = ui_helpers.StampedVar(value="")
        ttk.Label(r5, textvariable=self.gallery_status_var, style="Muted.TLabel", wraplength=330, justify="left").pack(side="left", padx=10)
        ttk.Separator(fx).pack(fill="x", padx=8, pady=4)
        ttk.Label(fx, justify="left", wraplength=560,
                  text="Clipboard:  click the mirror window, copy text on Windows, then press Ctrl+V - it pastes into the phone field that is "
                       "open. Alt+Shift+V types it as key presses (English only, works when Ctrl+V does not). Ctrl+C in the mirror window copies "
                       "the phone's selected text to Windows. Long-pressing 'Paste' on the phone itself uses the PHONE's clipboard, not Windows'.").pack(
            anchor="w", padx=8, pady=(2, 4))
        r6 = ttk.Frame(fx)
        r6.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(r6, text="Send my Windows clipboard to the phone page", command=self._safe(self._clipboard_to_phone_page)).pack(side="left")
        ttk.Label(r6, text="(then tap Copy on the phone page - works for any language, with or without mirroring)",
                  style="Muted.TLabel").pack(side="left", padx=8)

        # ---- quality ----
        q = ttk.LabelFrame(tab, text="Mirror quality (Android)  - defaults to MAXIMUM")
        q.pack(fill="x", padx=12, pady=6)
        pr = ttk.Frame(q)
        pr.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(pr, text="Preset:").pack(side="left")
        self.quality_preset_var = tk.StringVar()
        cb = ttk.Combobox(pr, textvariable=self.quality_preset_var, values=list(QUALITY_PRESETS), state="readonly", width=46)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", self._safe(lambda e: self._apply_quality_preset()))
        g = ttk.Frame(q)
        g.pack(fill="x", padx=8, pady=8)
        self.mirror_vars = {}
        for i, (key, label) in enumerate([("scrcpy_max_size", "Max size px (0 = native)"), ("scrcpy_bitrate_mbps", "Bitrate (Mbps)"),
                                          ("scrcpy_max_fps", "Max FPS")]):
            ttk.Label(g, text=label).grid(row=0, column=i * 2, sticky="w", padx=(0, 4))
            v = tk.StringVar(value=str(self.cfg.get(key, "")))
            self.mirror_vars[key] = v
            en = ttk.Entry(g, textvariable=v, width=7)
            en.grid(row=0, column=i * 2 + 1, padx=(0, 14))
            wire_field(en)
        self.screen_off_var = tk.BooleanVar(value=self.cfg.get("scrcpy_turn_screen_off", False))
        ttk.Checkbutton(g, text="Turn phone screen off while mirroring", variable=self.screen_off_var).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(g, text="Save quality", command=self._safe(self._save_mirror_settings)).grid(row=1, column=4, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Label(q, style="Muted.TLabel", wraplength=560, justify="left",
                  text="Max size is the limit of the LONGER side. 1200 on a 2400x1080 phone shows only half the pixels, so 'native' (0) is sharpest. "
                       "If the picture stutters on this laptop, pick 'High'. Changes apply the next time you start mirroring.").pack(anchor="w", padx=8, pady=(0, 8))
        self._sync_quality_preset_label()

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

    def _apply_quality_preset(self):
        size, mbps, fps = QUALITY_PRESETS[self.quality_preset_var.get()]
        self.mirror_vars["scrcpy_max_size"].set(str(size))
        self.mirror_vars["scrcpy_bitrate_mbps"].set(str(mbps))
        self.mirror_vars["scrcpy_max_fps"].set(str(fps))
        self._save_mirror_settings(quiet=True)
        self.mirror_status_var.set(f"Quality set: {self.quality_preset_var.get()} - applies the next time you start mirroring.")

    def _sync_quality_preset_label(self):
        current = (int(self.cfg.get("scrcpy_max_size") or 0), int(self.cfg.get("scrcpy_bitrate_mbps") or 0),
                   int(self.cfg.get("scrcpy_max_fps") or 0))
        for label, vals in QUALITY_PRESETS.items():
            if vals == current:
                self.quality_preset_var.set(label)
                return
        self.quality_preset_var.set("")

    def _save_mirror_settings(self, quiet: bool = False) -> bool:
        try:
            for key, var in self.mirror_vars.items():
                self.cfg[key] = int(var.get().strip() or 0)
        except ValueError:
            messagebox.showerror("Invalid value", "Size, bitrate and FPS must be whole numbers.")
            return False
        self.cfg["scrcpy_turn_screen_off"] = bool(self.screen_off_var.get())
        self.save_cfg(self.cfg)
        self._sync_quality_preset_label()
        if not quiet:
            self.mirror_status_var.set("Quality saved - applies the next time you start mirroring.")
        return True

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
        if not self._save_mirror_settings(quiet=True):      # use exactly what the quality fields show
            return
        self.mirror_status_var.set("Starting scrcpy ...")
        threading.Thread(target=self._mirror_thread, args=(serial,), name="Scrcpy", daemon=True).start()

    def _mirror_thread(self, serial):
        def on_line(line):
            # a file dragged onto the mirror window finished pushing -> ask Android to index it
            m = _PUSHED.match(line)
            if m and "scrcpy-server" not in line:
                name = Path(m.group(1)).name
                remote = f"{self.cfg.get('phone_gallery_dir', '/sdcard/DCIM/PLT').rstrip('/')}/{name}"
                if adb_helper.is_media(name):
                    threading.Thread(target=adb_helper.scan_media, args=(self.cfg["adb_path"], remote, serial),
                                     name="MediaScan", daemon=True).start()
                self.ui(lambda: self.gallery_status_var.set(f"Dropped file '{name}' is on the phone in {self.cfg.get('phone_gallery_dir')}"))
        ok, msg = scrcpy_helper.launch(self.cfg["scrcpy_path"], self.cfg, serial, on_line=on_line)
        self.ui(lambda: self.mirror_status_var.set(msg))

    # ---- laptop -> phone gallery over ADB ----
    def _send_files_to_phone_gallery(self):
        files = filedialog.askopenfilenames(title="Choose photos, videos or files to put on the phone")
        if not files:
            return
        serial = self.mirror_device_var.get() or None
        if not serial:
            ok, devices, msg = adb_helper.list_devices(self.cfg["adb_path"])
            if ok and devices:
                serial = devices[0]
            else:
                messagebox.showwarning("No phone found", (msg or "No Android phone is connected.") +
                                       "\n\nConnect it with USB (USB debugging ON) or pair it wirelessly first.")
                return
        self.gallery_status_var.set(f"Sending {len(files)} file(s) ...")
        threading.Thread(target=self._gallery_thread, args=(list(files), serial), name="GalleryPush", daemon=True).start()

    def _gallery_push_files(self, files):
        """Used by drag-and-drop on the Mirror page: push the dropped files to the phone gallery over ADB."""
        ok, devices, msg = adb_helper.list_devices(self.cfg["adb_path"])
        serial = self.mirror_device_var.get() or (devices[0] if ok and devices else None)
        if not serial:
            self.ui(lambda: self.gallery_status_var.set("No phone connected - connect it with USB or pair it first, then drop again."))
            return
        self.ui(lambda: self.gallery_status_var.set(f"Sending {len(files)} dropped file(s) ..."))
        self._gallery_thread(files, serial)

    def _gallery_thread(self, files, serial):
        results = adb_helper.push_to_phone(self.cfg["adb_path"], files, self.cfg.get("phone_gallery_dir", "/sdcard/DCIM/PLT"),
                                           self.cfg.get("phone_docs_dir", "/sdcard/Download/PLT"), serial,
                                           status_cb=lambda m: self.ui(lambda: self.gallery_status_var.set(m)))
        ok_n = 0
        for local, remote, msg in results:
            if remote:
                ok_n += 1
                try:
                    size = Path(local).stat().st_size
                except OSError:
                    size = 0
                self.server.history.add(KIND_FILE_ADB, name=Path(local).name, size=size, path=remote, via="adb")
        failed = [f"{Path(l).name}: {m}" for l, r, m in results if not r]
        text = f"{ok_n} of {len(files)} file(s) are now on the phone"
        if ok_n:
            text += f" in {self.cfg.get('phone_gallery_dir')} (photos/videos) / {self.cfg.get('phone_docs_dir')} (other files)."
        if failed:
            text += "  Failed: " + "; ".join(failed)[:300]
        log.info("Gallery push finished: %s", text)
        self.ui(lambda: self.gallery_status_var.set(text))

    def _clipboard_to_phone_page(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if not text.strip():
            self.gallery_status_var.set("The Windows clipboard has no text.")
            return
        self.server.text_store.add_to_phone(text)
        self.gallery_status_var.set(f"Clipboard ({len(text)} characters) is ready on the phone page - tap Copy there.")

    # ---- QR pairing ----
    def _start_qr_pairing(self):
        adb = self.cfg["adb_path"]
        ok, msg = adb_helper.check_adb_available(adb)
        if not ok:
            messagebox.showerror("ADB not available", msg)
            return
        self._cancel_qr_pairing()
        works, note = adb_helper.mdns_check(adb)
        if not works:
            self.pair_status_var.set("This computer's adb has no working mDNS service, so the QR cannot be detected. "
                                     "Use 'Pair with a code' below instead.  (adb said: " + note[:160] + ")")
            return
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

    def _pair_by_code(self):
        ok, msg = adb_helper.pair_with_code(self.cfg["adb_path"], self.pair_addr_var.get(), self.pair_code_var.get())
        self.pair_status_var.set(msg + ("  -> now enter the phone's main Wireless debugging address (ip:port) in section 3 and press Connect." if ok else ""))

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

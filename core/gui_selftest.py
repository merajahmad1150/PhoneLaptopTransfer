"""
core/gui_selftest.py
"Self-test (simulates a phone)": the tool acts as its own phone for a few seconds - opens the page, uploads a test file,
sends a text, downloads a shared test file - and reports each step with a time stamp and real speeds. Use it after an
upgrade or when something feels slow; the result is also written to the session log. All test files are removed afterwards.
"""

import os
import threading
import time
import urllib.request
from pathlib import Path
try:
    from tkinter import messagebox
except ImportError:          # headless test environment
    messagebox = None

from logger import get_logger

log = get_logger()


class SelfTestMixin:
    def _run_self_test(self):
        if not self.server.is_running:
            if not self._start_server():
                return
            self._refresh_server_ui()
        self.selftest_var.set("Self-test running ...")
        threading.Thread(target=self._self_test_thread, name="SelfTest", daemon=True).start()

    def _self_test_thread(self):
        port = self.cfg.get("server_port", 8765)
        base = f"http://127.0.0.1:{port}"
        steps, share = [], Path(self.cfg["share_folder"])
        size_mb = 8
        stamp = time.strftime("%Y%m%d_%H%M%S")
        up_name, dl_name = f"selftest_upload_{stamp}.bin", f"selftest_download_{stamp}.bin"

        def step(name, fn):
            t0 = time.time()
            try:
                detail = fn()
                ok = True
            except Exception as exc:
                detail, ok = f"FAILED: {exc}", False
            line = f"[{time.strftime('%H:%M:%S')}] {'OK  ' if ok else 'FAIL'} {name}: {detail}  ({time.time() - t0:.2f}s)"
            steps.append((ok, line))
            log.info("Self-test: %s", line)
            self.ui(lambda l=line: self.selftest_var.set(l))

        def page():
            with urllib.request.urlopen(base + "/", timeout=15) as r:
                return f"phone page answered HTTP {r.status}"

        def upload():
            data = os.urandom(size_mb * 1024 * 1024)
            req = urllib.request.Request(f"{base}/upload-raw?name={up_name}", data=data, method="PUT",
                                         headers={"X-Requested-With": "XMLHttpRequest"})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=120) as r:
                r.read()
            return f"{size_mb} MB uploaded at {size_mb / max(time.time() - t0, 0.001):.0f} MB/s (this laptop only, no Wi-Fi involved)"

        def text():
            import json
            req = urllib.request.Request(f"{base}/text/to-laptop", data=json.dumps({"text": "self-test text"}).encode(),
                                         method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return "text delivered: " + r.read().decode()[:60]

        def download():
            share.mkdir(parents=True, exist_ok=True)
            (share / dl_name).write_bytes(os.urandom(size_mb * 1024 * 1024))
            t0 = time.time()
            with urllib.request.urlopen(f"{base}/download/{dl_name}", timeout=120) as r:
                n = len(r.read())
            return f"{n / 1048576:.0f} MB downloaded at {n / 1048576 / max(time.time() - t0, 0.001):.0f} MB/s"

        def clipboard():
            from clipboard_helper import copy_text
            return "clipboard writable" if copy_text("PLT self-test") else "clipboard could NOT be written (another program holds it?)"

        step("Phone page", page)
        step("Upload (phone -> laptop)", upload)
        step("Text (phone -> laptop)", text)
        step("Download (laptop -> phone)", download)
        step("Clipboard", clipboard)
        # clean up
        for p in (Path(self.cfg["download_folder"]) / up_name, share / dl_name):
            try:
                p.unlink()
            except OSError:
                pass
        good = sum(1 for ok, _ in steps if ok)
        summary = f"Self-test finished: {good}/{len(steps)} steps passed. Test files removed."
        log.info(summary)
        report = "\n".join(l for _, l in steps)
        self.ui(lambda: (self.selftest_var.set(summary),
                         messagebox.showinfo("Self-test (simulated phone)", report + "\n\n" + summary)))

"""
core/web_server.py
The local web server (Flask on waitress). It serves:

  /                 the phone page (upload files/folders, download shared files, text)
  /upload-raw       FAST upload: one request per file, body streamed straight to disk
  /upload           old multipart upload (kept only for pages cached by a phone)
  /files, /download/<name>          laptop -> phone
  /text/to-laptop, /text/to-phone   text both ways (auto-copied to the laptop clipboard
                                    when it comes from the local Wi-Fi)
  /unlock           optional PIN gate (rate-limited)
  /room...          Shared Rooms (optional, isolated)
  /admin            control panel for the "web mode" - LOCAL NETWORK ONLY, never via the
                    public link

History: what the phone page shows disappears after `frontend_visible_hours`, but
everything stays saved on the laptop (data/history.jsonl, ReceivedText/,
ReceivedFromPhone/, ShareToPhone/).

Speed (v2.0): uploads are sent as raw per-file requests (no multipart parsing on the
laptop's CPU), waitress uses 256 KB socket buffers instead of its 8 KB default,
uploads up to 128 MB stay in RAM (no extra temp-file copy), larger ones spill to
BASE_DIR\\temp on the D drive (not C:), and a 1 GB request-size cap is lifted.
"""

import os
import secrets
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from flask import (Flask, abort, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from hmac import compare_digest

import net_utils
import room_manager
from history_store import (HistoryStore, KIND_FILE_FROM_PHONE, KIND_FILE_TO_PHONE)
from logger import get_logger, ring_since, stat_add
from public_url import PublicUrlWatcher
from qr_helper import make_qr_data_uri
from safe_names import safe_filename
from text_store import TextStore
from version import APP_NAME, VERSION
import clipboard_helper

log = get_logger()

MB = 1024 * 1024
_POLLING_PATHS = {"/files", "/text/to-phone", "/favicon.ico", "/upload-report"}
_MAX_SEGMENT = 150   # keeps full paths comfortably below Windows' 260-character limit


def _clip_segment(seg: str) -> str:
    if len(seg) <= _MAX_SEGMENT:
        return seg
    stem, dot, ext = seg.rpartition(".")
    if dot and len(ext) <= 10:
        return stem[:_MAX_SEGMENT - len(ext) - 1] + "." + ext
    return seg[:_MAX_SEGMENT]


def _segments(rel: str, fallback: str) -> list:
    segs = [_clip_segment(safe_filename(p)) for p in (rel or "").replace("\\", "/").split("/")
            if p not in ("", ".", "..")]
    return segs or [_clip_segment(safe_filename(fallback))]


class TransferServer:
    def __init__(self, cfg: dict, history: HistoryStore = None):
        self.cfg = cfg
        data_dir = Path(__file__).resolve().parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.history = history or HistoryStore(data_dir, Path(cfg["text_folder"]))
        self.text_store = TextStore(self.history)
        self.public = PublicUrlWatcher(cfg)
        self._share_index = {}        # file name -> history entry (when it was offered to the phone)
        self._share_lock = threading.Lock()
        for e in self.history.list([KIND_FILE_TO_PHONE]):
            self._share_index[e.get("name")] = e

        base_dir = Path(__file__).resolve().parent.parent / "web"
        self.app = Flask(__name__, template_folder=str(base_dir / "templates"),
                         static_folder=str(base_dir / "static"))
        self.app.config["MAX_CONTENT_LENGTH"] = None
        self.app.config["SESSION_COOKIE_HTTPONLY"] = True
        self.app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        self.app.config["PERMANENT_SESSION_LIFETIME"] = 12 * 3600
        self.app.json.ensure_ascii = False
        self.app.json.sort_keys = False
        self.app.wsgi_app = ProxyFix(self.app.wsgi_app, x_proto=1, x_for=1, x_host=1)
        self.app.secret_key = secrets.token_hex(32)

        self._httpd = None
        self._server_thread = None
        self._running = False
        self._cleanup_stop_event = threading.Event()
        self._cleanup_thread = None
        self._file_received_callbacks = []
        self._quit_callbacks = []
        self._pin_fail = {}           # ip -> [count, locked_until]
        self._pin_lock = threading.Lock()
        self._unique_lock = threading.Lock()
        self._qr_cache = {}
        self._probe_hits = {}         # ip -> recent 404 timestamps (internet scanners)
        self._probe_blocked = {}      # ip -> blocked until
        self._probe_lock = threading.Lock()
        self._register_routes()

    # ------------------------------------------------------------------ #
    # callbacks
    # ------------------------------------------------------------------ #
    def on_file_received(self, callback) -> None:
        self._file_received_callbacks.append(callback)

    def on_quit_requested(self, callback) -> None:
        self._quit_callbacks.append(callback)

    def _notify_file_received(self, path: Path) -> None:
        for cb in list(self._file_received_callbacks):
            try:
                cb(path)
            except Exception:
                log.error("A file-received listener raised an error", exc_info=True)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def visible_hours(self) -> float:
        try:
            return float(self.cfg.get("frontend_visible_hours", 6))
        except (TypeError, ValueError):
            return 6.0

    def client_info(self) -> dict:
        """ip: the real client address.
        via_tunnel: the request came through the internet/Tailscale, detected by proxy headers
          OR by the address that was typed (a *.ts.net name or the published public host) -
          the logs showed requests arriving via the public name from 127.0.0.1 with no proxy headers.
        is_lan: a device on the local network.  is_this_pc: the laptop itself."""
        orig = request.environ.get("werkzeug.proxy_fix.orig", {}) or {}
        raw_ip = orig.get("REMOTE_ADDR") or request.environ.get("REMOTE_ADDR", "")
        header_tunnel = any(h in request.headers for h in
                            ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "Forwarded"))
        host = (request.host or "").split(":")[0].lower()
        pub_host = (urlparse(self.public.state.get("url", "")).hostname or "").lower()
        host_public = host.endswith(".ts.net") or bool(pub_host and host == pub_host)
        via_tunnel = header_tunnel or host_public
        is_lan = (not via_tunnel) and net_utils.is_lan_address(raw_ip)
        is_this_pc = is_lan and (raw_ip in ("127.0.0.1", "::1") or raw_ip == net_utils.get_local_ip())
        return {"ip": request.remote_addr or raw_ip, "raw_ip": raw_ip, "via_tunnel": via_tunnel,
                "is_lan": is_lan, "is_this_pc": is_this_pc}

    def _external_base(self) -> str:
        """Scheme+host that OTHER devices should use for links/QR codes made on this request.
        When the page was opened through the public name, that is the https public URL (the
        old code produced http://...:8443, which never works)."""
        pub = urlparse(self.public.state.get("url", ""))
        host = (request.host or "").split(":")[0].lower()
        if pub.hostname and host == pub.hostname.lower():
            return f"{pub.scheme}://{pub.netloc}"
        return request.host_url.rstrip("/")

    @staticmethod
    def body_length():
        """Size of the request body. Per HTTP, a request with neither Content-Length
        nor chunked encoding has NO body (length 0) - that is how a browser sends an
        empty file. Chunked uploads are refused (None) because we need the size to
        check free space first."""
        cl = request.content_length
        if cl is not None:
            return cl
        if "chunked" in request.headers.get("Transfer-Encoding", "").lower():
            return None
        return 0

    def _check_space(self, dest_root: Path, need: int):
        try:
            free = shutil.disk_usage(str(dest_root)).free
        except OSError:
            return None
        floor = float(self.cfg.get("min_free_space_mb", 500)) * MB
        if free - need < floor:
            return (f"Not enough free space on the laptop ({free / 1024 ** 3:.1f} GB free, "
                    f"{need / MB:.0f} MB needed + {floor / MB:.0f} MB safety margin)")
        return None

    def _reserve_path(self, dest_root: Path, segments: list) -> Path:
        """Create an empty placeholder file with a unique name (file (1).ext, ...)
        so two simultaneous uploads can never pick the same name."""
        with self._unique_lock:
            target = dest_root.joinpath(*segments)
            target.parent.mkdir(parents=True, exist_ok=True)
            stem, suffix = target.stem, target.suffix
            candidate, i = target, 0
            while True:
                try:
                    with open(candidate, "xb"):
                        return candidate
                except FileExistsError:
                    i += 1
                    candidate = target.parent / f"{stem} ({i}){suffix}"

    def _stream_to_disk(self, dest_root: Path, rel: str, fallback: str, label_prefix: str = ""):
        """Core of the fast upload: stream the request body straight into the
        final folder. Returns (final_path, size_bytes, seconds)."""
        segments = _segments(rel, fallback)
        final = self._reserve_path(dest_root, segments)
        part = final.with_name(final.name + ".part")
        expected = self.body_length()
        start = time.time()
        written = 0
        try:
            stream = request.stream
            with open(part, "wb", buffering=1024 * 1024) as out:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
            if expected is not None and written != expected:
                raise IOError(f"incomplete upload: got {written} of {expected} bytes")
            os.replace(part, final)
        except BaseException:
            for p in (part, final):
                try:
                    p.unlink()
                except OSError:
                    pass
            raise
        return final, written, time.time() - start

    # ------------------------------------------------------------------ #
    # share index (laptop -> phone files)
    # ------------------------------------------------------------------ #
    def register_shared_file(self, path: Path) -> None:
        """Called when a file is offered to the phone (GUI button, admin upload,
        or noticed in the share folder). Starts its visibility timer."""
        path = Path(path)
        try:
            size = path.stat().st_size
        except OSError:
            return
        with self._share_lock:
            entry = self.history.add(KIND_FILE_TO_PHONE, name=path.name, size=size, path=str(path))
            self._share_index[path.name] = entry

    def _sync_share_index(self, share_dir: Path) -> None:
        """Notice files dropped into ShareToPhone by hand (Explorer) and start
        their timer the first time they are seen (or when modified later)."""
        try:
            entries = [e for e in share_dir.iterdir() if e.is_file()]
        except OSError:
            return
        for p in entries:
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            known = self._share_index.get(p.name)
            if known is None or mtime > known["ts"] + 2:
                self.register_shared_file(p)
                log.info("Noticed new file in the share folder: '%s'", p.name)

    # ------------------------------------------------------------------ #
    # routes
    # ------------------------------------------------------------------ #
    def _ctx(self, **extra):
        ctx = {"app_name": APP_NAME, "version": VERSION, "visible_hours": self.visible_hours(),
               "parallel_uploads": int(self.cfg.get("parallel_uploads", 3))}
        ctx.update(extra)
        return ctx

    def _register_routes(self):
        app = self.app

        @app.before_request
        def start_timer():
            g.t0 = time.time()

        @app.before_request
        def block_scanners():
            """Internet bots probe every public address for /.env, /.git/config, *.php ...
            After 15 'not found' answers in a minute the address is refused for 10 minutes."""
            ip = request.remote_addr or ""
            with self._probe_lock:
                until = self._probe_blocked.get(ip, 0)
            if until > time.time():
                stat_add("blocked_scanner_requests")
                return jsonify({"ok": False, "error": "Too many invalid requests"}), 429
            return None

        @app.before_request
        def require_pin_if_enabled():
            if not self.cfg.get("require_access_pin"):
                return None
            ep = request.endpoint or ""
            if ep in ("unlock", "static", "favicon") or ep.startswith("room"):
                return None
            if session.get("unlocked"):
                return None
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/admin/api"):
                return jsonify({"ok": False, "error": "PIN required", "pin_required": True}), 401
            return redirect(url_for("unlock", next=request.path))

        @app.after_request
        def finish(response):
            if request.endpoint == "static":
                response.headers["Cache-Control"] = "public, max-age=3600"
            elif request.endpoint not in ("download", "room_download", "admin_received"):
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            self._note_probe(response)
            self._access_log(response)
            return response

        @app.errorhandler(Exception)
        def handle_any_error(exc):
            code = exc.code if isinstance(exc, HTTPException) else 500
            if code >= 500:
                log.error("Request error on %s %s: %s", request.method, request.path, exc, exc_info=True)
            else:
                log.debug("Client error on %s: %s (HTTP %s)", request.path, getattr(exc, "name", exc), code)
            if request.method == "GET" and "text/html" in request.headers.get("Accept", "") \
                    and request.headers.get("X-Requested-With") != "XMLHttpRequest" and code in (403, 404):
                return render_template("error.html", **self._ctx(code=code, message=str(getattr(exc, "description", exc)))), code
            return jsonify({"ok": False, "error": getattr(exc, "description", None) or str(exc)}), code

        # ---------------- PIN ----------------
        @app.route("/unlock", methods=["GET", "POST"])
        def unlock():
            error = None
            ip = self.client_info()["ip"]
            if request.method == "POST":
                wait = self._pin_locked_for(ip)
                if wait > 0:
                    log.warning("PIN attempt from %s blocked (locked for %d more seconds)", ip, wait)
                    error = f"Too many wrong attempts. Try again in {wait} seconds."
                    return render_template("unlock.html", error=error, **self._ctx()), 429
                submitted = request.form.get("pin", "").strip()
                expected = str(self.cfg.get("access_pin", ""))
                if expected and compare_digest(submitted.encode(), expected.encode()):
                    session["unlocked"] = True
                    session.permanent = True
                    self._pin_reset(ip)
                    log.info("PIN accepted from %s - access unlocked for this browser", ip)
                    nxt = request.args.get("next") or "/"
                    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
                        nxt = "/"
                    return redirect(nxt)
                fails = self._pin_fail_record(ip)
                log.warning("Incorrect PIN from %s (wrong attempt #%d)", ip, fails)
                error = "Incorrect PIN, try again."
            return render_template("unlock.html", error=error, **self._ctx())

        @app.route("/favicon.ico", endpoint="favicon")
        def favicon():
            return send_from_directory(app.static_folder, "favicon.ico", max_age=86400)

        # ---------------- main page ----------------
        @app.route("/")
        def index():
            return render_template("index.html", **self._ctx(**self._lan_tip_context("/")))

        # ---------------- uploads (phone -> laptop) ----------------
        @app.route("/upload-raw", methods=["PUT", "POST"])
        def upload_raw():
            dest_root = Path(self.cfg["download_folder"])
            dest_root.mkdir(parents=True, exist_ok=True)
            cl = self.body_length()
            if cl is None:
                return jsonify({"ok": False, "error": "Content-Length is required (chunked uploads are not supported)"}), 411
            err = self._check_space(dest_root, cl)
            if err:
                log.error("Upload refused: %s", err)
                stat_add("uploads_refused_disk_full")
                return jsonify({"ok": False, "error": err}), 507
            rel = request.args.get("name", "")
            ci = self.client_info()
            try:
                final, size, secs = self._stream_to_disk(dest_root, rel, "file")
            except Exception as exc:
                stat_add("uploads_failed")
                log.error("Upload of '%s' from %s FAILED: %s", rel, ci["ip"], exc, exc_info=True)
                return jsonify({"ok": False, "error": f"Could not save the file: {exc}"}), 500
            self._after_received(final, rel, size, secs, ci)
            return jsonify({"ok": True, "saved": str(final.relative_to(dest_root)), "bytes": size})

        @app.route("/upload", methods=["POST"])
        def upload_legacy():
            files = request.files.getlist("files")
            if not files:
                return jsonify({"ok": False, "error": "No files received"}), 400
            rel_paths = request.form.getlist("paths")
            dest_root = Path(self.cfg["download_folder"])
            dest_root.mkdir(parents=True, exist_ok=True)
            ci = self.client_info()
            saved = []
            for idx, f in enumerate(files):
                if not f.filename:
                    continue
                rel = rel_paths[idx] if idx < len(rel_paths) and rel_paths[idx] else f.filename
                final = self._reserve_path(dest_root, _segments(rel, f.filename))
                t0 = time.time()
                f.save(final)
                self._after_received(final, rel, final.stat().st_size, time.time() - t0, ci)
                saved.append(str(final.relative_to(dest_root)))
            return jsonify({"ok": True, "saved": saved})

        @app.route("/upload-report", methods=["POST"])
        def upload_report():
            data = request.get_json(silent=True, force=True) or {}
            try:
                n, b, ms = int(data.get("files", 0)), int(data.get("bytes", 0)), float(data.get("ms", 0))
            except (TypeError, ValueError):
                return jsonify({"ok": False}), 400
            if ms > 0 and b > 0:
                log.info("Upload batch from %s: %d file(s), %.2f MB in %.1fs = %.2f MB/s (measured on the phone, includes Wi-Fi)",
                         self.client_info()["ip"], n, b / MB, ms / 1000, (b / MB) / (ms / 1000))
            return jsonify({"ok": True})

        # ---------------- laptop -> phone ----------------
        @app.route("/files")
        def list_files():
            share_dir = Path(self.cfg["share_folder"])
            share_dir.mkdir(parents=True, exist_ok=True)
            self._sync_share_index(share_dir)
            hours = self.visible_hours()
            cutoff = time.time() - hours * 3600 if hours > 0 else 0
            items = []
            with self._share_lock:
                index = dict(self._share_index)
            for name, e in index.items():
                if cutoff and e["ts"] < cutoff:
                    continue
                p = share_dir / name
                try:
                    st = p.stat()
                except OSError:
                    continue
                if not p.is_file():
                    continue
                items.append({"name": name, "size": st.st_size, "added": int(e["ts"]), "modified": int(st.st_mtime)})
            items.sort(key=lambda i: i["added"], reverse=True)
            return jsonify({"ok": True, "files": items, "visible_hours": hours})

        @app.route("/download/<path:filename>")
        def download(filename):
            share_dir = Path(self.cfg["share_folder"]).resolve()
            safe_name = safe_filename(filename)
            target = (share_dir / safe_name).resolve()
            if share_dir not in target.parents:
                log.warning("Blocked suspicious download request: %s", filename)
                return jsonify({"ok": False, "error": "Invalid filename"}), 400
            if not target.is_file():
                return jsonify({"ok": False, "error": "File not found"}), 404
            self._log_download(target.name)
            return send_from_directory(share_dir, safe_name, as_attachment=True, max_age=0)

        # ---------------- text ----------------
        @app.route("/text/to-laptop", methods=["POST"])
        def receive_text():
            data = request.get_json(silent=True) or {}
            text = data.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return jsonify({"ok": False, "error": "No text provided"}), 400
            ci = self.client_info()
            copied = False
            if self.cfg.get("auto_copy_text", True):
                if ci["is_this_pc"]:
                    log.info("Text typed on this laptop itself (%d chars) - clipboard left untouched", len(text))
                elif ci["is_lan"]:
                    copied = clipboard_helper.copy_text(text)
                    if copied:
                        log.info("Text from %s (%d chars) was copied to the laptop clipboard automatically", ci["ip"], len(text))
                    else:
                        log.warning("Text from %s could not be copied to the clipboard automatically", ci["ip"])
                else:
                    log.info("Text arrived over the internet/tunnel from %s - NOT auto-copied (only local Wi-Fi text is)", ci["ip"])
            entry = self.text_store.add_to_laptop(text, via="lan" if ci["is_lan"] else "internet", copied=copied)
            stat_add("texts_received")
            log.info("Received text from %s (%d characters, id %d, %s)", ci["ip"], len(text), entry["id"],
                     "local Wi-Fi" if ci["is_lan"] else "internet")
            return jsonify({"ok": True, "id": entry["id"], "copied": copied})

        @app.route("/text/to-phone")
        def text_to_phone():
            since = request.args.get("since", default=0, type=int)
            return jsonify({"ok": True, "texts": self.text_store.list_to_phone(since, self.visible_hours())})

        self._register_room_routes()
        self._register_admin_routes()

    # ------------------------------------------------------------------ #
    def _after_received(self, final: Path, rel: str, size: int, secs: float, ci: dict):
        stat_add("files_received")
        stat_add("bytes_received", size)
        self.history.add(KIND_FILE_FROM_PHONE, name=str(rel), size=size, path=str(final),
                         via="lan" if ci["is_lan"] else "internet")
        took = f"{secs:.2f}s = {(size / MB) / secs:.0f} MB/s" if secs >= 0.05 else "<0.05s"
        log.info("Received '%s' (%.2f MB) from %s -> %s  [saved to disk in %s]",
                 rel, size / MB, ci["ip"], final, took)
        self._notify_file_received(final)

    # ---------------- PIN lockout ----------------
    def _pin_locked_for(self, ip: str) -> int:
        with self._pin_lock:
            rec = self._pin_fail.get(ip)
            if not rec:
                return 0
            return max(0, int(rec[1] - time.time() + 0.999))

    def _pin_fail_record(self, ip: str) -> int:
        with self._pin_lock:
            rec = self._pin_fail.setdefault(ip, [0, 0.0])
            rec[0] += 1
            if rec[0] >= 5:
                rec[1] = time.time() + min(900, 30 * (2 ** (rec[0] - 5)))
            return rec[0]

    def _pin_reset(self, ip: str):
        with self._pin_lock:
            self._pin_fail.pop(ip, None)

    # ---------------- scanner defence ----------------
    def _note_probe(self, response):
        try:
            if response.status_code != 404:
                return
            ci = self.client_info()
            if ci["is_lan"]:
                return
            ip, now = ci["ip"], time.time()
            with self._probe_lock:
                hits = [t for t in self._probe_hits.get(ip, []) if now - t < 60] + [now]
                self._probe_hits[ip] = hits
                if len(hits) >= 15 and self._probe_blocked.get(ip, 0) < now:
                    self._probe_blocked[ip] = now + 600
                    self._probe_hits.pop(ip, None)
                    stat_add("scanners_blocked")
                    log.warning("Blocked %s for 10 minutes: %d invalid requests in under a minute "
                                "(an internet scanner probing paths such as %s). Nothing was exposed.",
                                ip, len(hits), request.path)
        except Exception:
            log.debug("probe tracking failed", exc_info=True)

    # ---------------- access log ----------------
    def _access_log(self, response):
        try:
            path = request.path
            status = response.status_code
            if status == 404 and not self.client_info()["is_lan"]:
                return   # internet probes are counted/blocked above, not logged one by one
            if status < 400 and (path.startswith("/static") or path in _POLLING_PATHS
                                 or path.startswith("/admin/api") or request.method in ("PUT",)
                                 or path.startswith("/download/") or path.endswith("/download")
                                 or "/download/" in path or path.endswith("/upload-raw")
                                 or path.endswith("/files") or path.endswith("/texts") or path.endswith("/text")):
                return
            ci = self.client_info()
            ms = (time.time() - getattr(g, "t0", time.time())) * 1000
            slow = f" ({ms:.0f} ms)" if ms > 1500 else ""
            log.debug("%s %s -> %s from %s [%s]%s", request.method, path, status, ci["ip"],
                      "internet" if ci["via_tunnel"] else "local", slow)
        except Exception:
            pass

    def _log_download(self, name: str, prefix: str = "") -> None:
        """One line per download. Browsers fetch big files with several parallel
        Range requests; only the first one (bytes=0-) is logged."""
        rng = request.headers.get("Range")
        if rng and not rng.replace(" ", "").startswith("bytes=0-"):
            return
        stat_add("downloads")
        log.info("%sSending '%s' to %s%s", prefix, name, self.client_info()["ip"],
                 " (browser may use several parallel range requests)" if rng else "")

    def _lan_tip_context(self, path_suffix: str = "/") -> dict:
        ci = self.client_info()
        lan_url = None
        if ci["via_tunnel"]:
            lan_url = f"http://{net_utils.get_local_ip()}:{self.cfg.get('server_port', 8765)}{path_suffix}"
        return {"via_tunnel": ci["via_tunnel"], "lan_url": lan_url}

    # ------------------------------------------------------------------ #
    # Shared Rooms
    # ------------------------------------------------------------------ #
    def _room_guard(self, code: str):
        if not self.cfg.get("rooms_enabled") or not room_manager.room_exists(code):
            return jsonify({"ok": False, "error": "Room not found or expired"}), 404
        return None

    def _register_room_routes(self):
        app = self.app

        @app.route("/room")
        def room_new():
            if not self.cfg.get("rooms_enabled"):
                return render_template("rooms_disabled.html", **self._ctx()), 403
            ip = self.client_info()["ip"]
            if room_manager.rate_limited(ip):
                return jsonify({"ok": False, "error": "Too many rooms created - wait a minute"}), 429
            room_manager.cleanup_expired(self.cfg.get("room_max_age_hours", 24))
            code = room_manager.create_room(ip, int(self.cfg.get("room_max_rooms", 20)))
            if not code:
                return jsonify({"ok": False, "error": "The room limit has been reached - try again later"}), 503
            return redirect(url_for("room_page", code=code))

        @app.route("/room/<code>")
        def room_page(code):
            if not self.cfg.get("rooms_enabled"):
                return render_template("rooms_disabled.html", **self._ctx()), 403
            code = code.upper()
            if not room_manager.room_exists(code):
                return redirect(url_for("room_new"))
            room_manager.touch_room(code)
            room_url = self._external_base() + url_for("room_page", code=code)
            return render_template("room.html", **self._ctx(code=code, room_url=room_url,
                                   qr_data_uri=make_qr_data_uri(room_url), **self._lan_tip_context(f"/room/{code}")))

        @app.route("/room/<code>/upload-raw", methods=["PUT", "POST"])
        def room_upload_raw(code):
            code = code.upper()
            bad = self._room_guard(code)
            if bad:
                return bad
            cl = self.body_length()
            if cl is None:
                return jsonify({"ok": False, "error": "Content-Length is required (chunked uploads are not supported)"}), 411
            max_mb = float(self.cfg.get("room_max_file_mb", 500))
            total_mb = float(self.cfg.get("room_max_total_mb", 2048))
            if cl > max_mb * MB:
                return jsonify({"ok": False, "error": f"File exceeds the {max_mb:.0f} MB room limit"}), 413
            if room_manager.room_bytes(code) + cl > total_mb * MB:
                return jsonify({"ok": False, "error": f"This room is full ({total_mb:.0f} MB total)"}), 413
            dest_root = room_manager.room_dir(code)
            dest_root.mkdir(parents=True, exist_ok=True)
            err = self._check_space(dest_root, cl)
            if err:
                return jsonify({"ok": False, "error": err}), 507
            rel = request.args.get("name", "")
            try:
                final, size, secs = self._stream_to_disk(dest_root, rel, "file")
            except Exception as exc:
                log.error("Room %s upload of '%s' FAILED: %s", code, rel, exc, exc_info=True)
                return jsonify({"ok": False, "error": f"Could not save the file: {exc}"}), 500
            room_manager.add_room_bytes(code, size)
            room_manager.touch_room(code)
            log.info("Room %s: received '%s' (%.2f MB) from %s", code, rel, size / MB, self.client_info()["ip"])
            return jsonify({"ok": True, "saved": str(final.relative_to(dest_root)), "bytes": size})

        @app.route("/room/<code>/files")
        def room_files(code):
            code = code.upper()
            bad = self._room_guard(code)
            if bad:
                return bad
            room_manager.touch_room(code)
            share_dir = room_manager.room_dir(code)
            items = []
            for entry in sorted(share_dir.rglob("*")):
                if entry.is_file() and not entry.name.endswith(".part"):
                    st = entry.stat()
                    items.append({"name": str(entry.relative_to(share_dir)).replace("\\", "/"),
                                  "size": st.st_size, "added": int(st.st_mtime), "modified": int(st.st_mtime)})
            items.sort(key=lambda i: i["added"], reverse=True)
            return jsonify({"ok": True, "files": items})

        @app.route("/room/<code>/download/<path:filename>")
        def room_download(code, filename):
            code = code.upper()
            bad = self._room_guard(code)
            if bad:
                return bad
            room_dir = room_manager.room_dir(code).resolve()
            target = (room_dir / filename).resolve()
            if room_dir not in target.parents:
                log.warning("Room %s: blocked suspicious download request: %s", code, filename)
                return jsonify({"ok": False, "error": "Invalid filename"}), 400
            if not target.is_file():
                return jsonify({"ok": False, "error": "File not found"}), 404
            room_manager.touch_room(code)
            self._log_download(target.name, prefix=f"Room {code}: ")
            return send_from_directory(room_dir, target.relative_to(room_dir).as_posix(), as_attachment=True, max_age=0)

        @app.route("/room/<code>/text", methods=["POST"])
        def room_text_post(code):
            code = code.upper()
            bad = self._room_guard(code)
            if bad:
                return bad
            data = request.get_json(silent=True) or {}
            text = data.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return jsonify({"ok": False, "error": "No text provided"}), 400
            cap = int(self.cfg.get("room_max_text_kb", 256)) * 1024
            if len(text.encode("utf-8", "ignore")) > cap:
                return jsonify({"ok": False, "error": f"Text is too long for a room (max {cap // 1024} KB)"}), 413
            entry = room_manager.add_room_text(code, text)
            log.info("Room %s: received text (%d characters)", code, len(text))
            return jsonify({"ok": True, "id": entry["id"]})

        @app.route("/room/<code>/texts")
        def room_texts_get(code):
            code = code.upper()
            bad = self._room_guard(code)
            if bad:
                return bad
            since = request.args.get("since", default=0, type=int)
            return jsonify({"ok": True, "texts": room_manager.list_room_texts(code, since)})

    # ------------------------------------------------------------------ #
    # Admin dashboard (web mode) - local network only
    # ------------------------------------------------------------------ #
    def _local_only(self):
        ci = self.client_info()
        if not ci["is_lan"]:
            log.warning("Blocked /admin access from %s (%s) - the control panel is local-network only",
                        ci["ip"], "internet/tunnel" if ci["via_tunnel"] else "non-local address")
            abort(403, "The control panel can only be opened from the same Wi-Fi/network as the laptop.")

    def _qr(self, url: str) -> str:
        if not url:
            return ""
        if url not in self._qr_cache:
            if len(self._qr_cache) > 20:
                self._qr_cache.clear()
            self._qr_cache[url] = make_qr_data_uri(url, box_size=6)
        return self._qr_cache[url]

    def state_snapshot(self) -> dict:
        port = self.cfg.get("server_port", 8765)
        lan = f"http://{net_utils.get_local_ip()}:{port}"
        pub = dict(self.public.state)
        return {"app": APP_NAME, "version": VERSION, "running": self._running, "port": port,
                "lan_url": lan, "lan_qr": self._qr(lan), "public": pub,
                "public_qr": self._qr(pub.get("url", "")), "counts": self.history.counts(),
                "visible_hours": self.visible_hours(), "download_folder": self.cfg["download_folder"],
                "share_folder": self.cfg["share_folder"], "text_folder": self.cfg["text_folder"],
                "auto_copy_text": bool(self.cfg.get("auto_copy_text", True))}

    def _register_admin_routes(self):
        app = self.app

        @app.route("/admin")
        def admin_page():
            self._local_only()
            return render_template("admin.html", **self._ctx())

        @app.route("/admin/api/state")
        def admin_state():
            self._local_only()
            return jsonify({"ok": True, **self.state_snapshot()})

        @app.route("/admin/api/history")
        def admin_history():
            self._local_only()
            items = self.history.list(include_cleared=False)[-300:]
            return jsonify({"ok": True, "items": list(reversed(items))})

        @app.route("/admin/api/log")
        def admin_log():
            self._local_only()
            after = request.args.get("after", default=0, type=int)
            seq, lines = ring_since(after)
            return jsonify({"ok": True, "seq": seq, "lines": lines})

        @app.route("/admin/api/send-text", methods=["POST"])
        def admin_send_text():
            self._local_only()
            text = (request.get_json(silent=True) or {}).get("text", "")
            if not isinstance(text, str) or not text.strip():
                return jsonify({"ok": False, "error": "No text provided"}), 400
            self.text_store.add_to_phone(text)
            log.info("Dashboard: queued text for the phone (%d characters)", len(text))
            return jsonify({"ok": True})

        @app.route("/admin/api/share-upload", methods=["PUT", "POST"])
        def admin_share_upload():
            self._local_only()
            dest_root = Path(self.cfg["share_folder"])
            dest_root.mkdir(parents=True, exist_ok=True)
            cl = self.body_length()
            if cl is None:
                return jsonify({"ok": False, "error": "Content-Length is required (chunked uploads are not supported)"}), 411
            err = self._check_space(dest_root, cl)
            if err:
                return jsonify({"ok": False, "error": err}), 507
            name = request.args.get("name", "file")
            try:
                final, size, secs = self._stream_to_disk(dest_root, name, "file")
            except Exception as exc:
                log.error("Dashboard share-upload of '%s' FAILED: %s", name, exc, exc_info=True)
                return jsonify({"ok": False, "error": str(exc)}), 500
            self.register_shared_file(final)
            log.info("Dashboard: '%s' (%.2f MB) added to the share folder for the phone", final.name, size / MB)
            return jsonify({"ok": True, "saved": final.name})

        @app.route("/admin/api/received/<path:rel>")
        def admin_received(rel):
            self._local_only()
            root = Path(self.cfg["download_folder"]).resolve()
            target = (root / rel).resolve()
            if root not in target.parents or not target.is_file():
                abort(404)
            return send_from_directory(root, target.relative_to(root).as_posix(), as_attachment=True, max_age=0)

        @app.route("/admin/api/clear-history", methods=["POST"])
        def admin_clear():
            self._local_only()
            n = self.history.clear_visible()
            log.info("Dashboard: history list cleared (%d item(s) hidden; saved data kept on disk)", n)
            return jsonify({"ok": True, "hidden": n})

        @app.route("/admin/api/quit", methods=["POST"])
        def admin_quit():
            self._local_only()
            log.warning("Quit requested from the web dashboard by %s", self.client_info()["ip"])
            threading.Timer(0.5, self._fire_quit).start()
            return jsonify({"ok": True})

    def _fire_quit(self):
        for cb in list(self._quit_callbacks):
            try:
                cb()
            except Exception:
                log.error("Quit callback failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self):
        if self._running:
            log.debug("Server start requested but already running")
            return
        from waitress.server import create_server

        port = int(self.cfg["server_port"])
        host = self.cfg.get("bind_host", "0.0.0.0")
        buf = int(self.cfg.get("socket_buffer_kb", 256)) * 1024
        tuned = dict(
            threads=int(self.cfg.get("server_threads", 8)),
            recv_bytes=buf, send_bytes=buf,
            inbuf_overflow=int(float(self.cfg.get("inbuf_overflow_mb", 128)) * MB),
            outbuf_overflow=4 * MB,
            max_request_body_size=1024 * 1024 * MB,   # effectively unlimited (1 TB)
            channel_timeout=900, connection_limit=200, backlog=1024,
            asyncore_use_poll=True,
        )
        try:
            self._httpd = create_server(self.app, host=host, port=port, **tuned)
        except (ValueError, TypeError) as exc:
            # An older/newer waitress that doesn't know one of the tuning names:
            # keep going with safe defaults instead of failing to start.
            log.warning("waitress rejected the speed-tuning options (%s); starting with defaults", exc)
            tuned = {"threads": tuned["threads"]}
            self._httpd = create_server(self.app, host=host, port=port, **tuned)
        except OSError as exc:
            log.error("Failed to bind the server to %s:%s - %s", host, port, exc, exc_info=True)
            raise

        self._server_thread = threading.Thread(target=self._httpd.run, name="WaitressServer", daemon=True)
        self._server_thread.start()
        self._running = True
        log.info("Server started on %s:%s (waitress; settings: %s)", host, port,
                 ", ".join(f"{k}={v}" for k, v in tuned.items()))

        room_manager.purge_orphans()
        self._cleanup_stop_event.clear()
        self._cleanup_thread = threading.Thread(target=self._room_cleanup_loop, name="RoomCleanup", daemon=True)
        self._cleanup_thread.start()
        self._warned_public = set()
        self.public.on_change(self._public_changed)
        self.public.start()

    def _public_changed(self, state: dict):
        url = state.get("url", "")
        if state.get("is_funnel") and url and not self.cfg.get("require_access_pin") and url not in self._warned_public:
            self._warned_public.add(url)
            log.warning("Your PUBLIC link is live WITHOUT an access PIN: %s  Internet bots scan public links within hours. "
                        "Turn on Public Access > 'Ask visitors for a PIN'.", url)

    def _room_cleanup_loop(self):
        while not self._cleanup_stop_event.wait(300):
            try:
                room_manager.cleanup_expired(self.cfg.get("room_max_age_hours", 24))
            except Exception:
                log.error("Room cleanup loop hit an error", exc_info=True)

    def stop(self):
        if not self._running or not self._httpd:
            log.debug("Server stop requested but not running")
            return
        log.info("Stopping server...")
        self._cleanup_stop_event.set()
        self.public.stop()
        try:
            self._httpd.close()
        except Exception:
            log.error("Error while closing the server socket", exc_info=True)
        if self._server_thread:
            self._server_thread.join(timeout=5)
        self._running = False
        log.info("Server stopped")

    @property
    def is_running(self) -> bool:
        return self._running

"""
core/web_server.py
The core "Wi-Fi web transfer" feature. Runs a small Flask server that:
  - Serves a mobile-friendly page at "/" with an upload drop-zone (files
    AND whole folders) and a browsable list of files the laptop is sharing.
  - Accepts uploads at POST /upload and saves them into the configured
    download_folder (any file type, streamed to disk to handle large
    files; folder structure preserved if the client sends relative paths).
  - Lists files in the configured share_folder at GET /files (JSON).
  - Serves files for download at GET /download/<filename>.
  - Text sharing (any length, either direction) at POST /text/to-laptop
    and GET /text/to-phone, backed by the shared TextStore.
  - An optional PIN gate (/unlock) - OFF by default for LAN use, but the
    Public Access tab strongly suggests turning it on before publishing
    to the internet, since without it anyone with the
    public URL could upload/download files with no authentication at all.
  - Shared Rooms (/room, /room/<code>/...) - OFF by default. Lets a
    stranger with the public link get their own isolated room (separate
    storage + text feed from the owner's personal share) to pair their
    own laptop+phone. Deliberately exempt from the PIN gate above, since
    the PIN protects the owner's personal share, not the public rooms
    feature that's the whole point of publishing the link to others.

Runs behind ProxyFix so it correctly detects "https" when reached through
Tailscale Funnel: Funnel terminates TLS at its edge and forwards the
request to this local server as plain HTTP, so without ProxyFix trusting
the X-Forwarded-Proto header Funnel sends, Flask would think every
request (even the public HTTPS one) arrived over http - which produced
room links with the wrong scheme baked in (they'd never load, since
Funnel doesn't serve plain HTTP on the public hostname at all).

Runs in its own thread so the Tkinter GUI stays responsive. Designed to
never take the whole app down: every route wraps its logic in try/except
and logs + returns a clear JSON error instead of crashing.
"""

import os
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

import net_utils
import room_manager
from logger import get_logger
from qr_helper import make_qr_data_uri
from safe_names import safe_filename
from text_store import TextStore

log = get_logger()


class TransferServer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.text_store = TextStore()
        base_dir = Path(__file__).resolve().parent.parent / "web"
        self.app = Flask(
            __name__,
            template_folder=str(base_dir / "templates"),
            static_folder=str(base_dir / "static"),
        )
        self.app.config["MAX_CONTENT_LENGTH"] = None  # allow large files (videos etc.)
        # Trust X-Forwarded-Proto/-For/-Host from a reverse proxy (Tailscale
        # Funnel) so request.scheme / request.host_url report "https"
        # correctly for publicly-accessed requests, not just LAN ones.
        self.app.wsgi_app = ProxyFix(self.app.wsgi_app, x_proto=1, x_for=1, x_host=1)
        # New random secret each run, just for signing the "unlocked" cookie -
        # not meant to persist across restarts, and nothing sensitive is
        # stored in the session besides a boolean.
        self.app.secret_key = secrets.token_hex(32)
        self._server_thread = None
        self._httpd = None
        self._running = False
        self._cleanup_thread = None
        self._cleanup_stop_event = threading.Event()
        self._file_received_callbacks = []
        self._register_routes()

    def on_file_received(self, callback) -> None:
        """Register a callback(full_path: Path) fired whenever a file
        finishes uploading from the phone - lets the GUI show a live
        "Recently Received" list instead of the user having to go dig
        through Explorer to find what just arrived."""
        self._file_received_callbacks.append(callback)

    def _notify_file_received(self, path: Path) -> None:
        for callback in list(self._file_received_callbacks):
            try:
                callback(path)
            except Exception:
                log.error("A file-received listener raised an error", exc_info=True)

    # ------------------------------------------------------------------ #
    # Route setup
    # ------------------------------------------------------------------ #
    def _register_routes(self):
        app = self.app

        @app.after_request
        def no_cache(response):
            # Every response here reflects live server state (file lists,
            # text feeds) that can change from one request to the next -
            # never let a browser or intermediate proxy serve a cached
            # copy instead of asking again.
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            return response

        @app.after_request
        def access_log(response):
            # Full transparency on every request, not just the ones with
            # their own dedicated log line - nothing about traffic through
            # this server should be invisible.
            log.debug("%s %s -> %s", request.method, request.path, response.status)
            return response

        @app.errorhandler(Exception)
        def handle_any_error(exc):
            # Catch-all so a single bad request never crashes the server
            # or leaves the phone with a blank/broken response.
            code = exc.code if isinstance(exc, HTTPException) else 500
            if code >= 500:
                log.error("Request error on %s: %s", request.path, exc, exc_info=True)
            else:
                # Routine client-side stuff (404s, bad requests) - log quietly,
                # no need for a full traceback or an ERROR-level entry.
                log.debug("Client error on %s: %s (HTTP %s)", request.path, exc, code)
            return jsonify({"ok": False, "error": str(exc)}), code

        @app.before_request
        def require_pin_if_enabled():
            if not self.cfg.get("require_access_pin"):
                return None
            if request.endpoint in ("unlock", "static", "favicon"):
                return None
            if request.endpoint and request.endpoint.startswith("room"):
                return None  # rooms are the public-sharing feature, not gated by the owner's PIN
            if session.get("unlocked"):
                return None
            return redirect(url_for("unlock", next=request.path))

        @app.route("/unlock", methods=["GET", "POST"])
        def unlock():
            error = None
            if request.method == "POST":
                submitted = request.form.get("pin", "")
                expected = str(self.cfg.get("access_pin", ""))
                if expected and submitted == expected:
                    session["unlocked"] = True
                    log.info("PIN accepted, access unlocked for this session")
                    return redirect(request.args.get("next") or url_for("index"))
                log.warning("Incorrect PIN attempt")
                error = "Incorrect PIN, try again."
            return render_template("unlock.html", error=error)

        @app.route("/favicon.ico")
        def favicon():
            # Browsers request this automatically; without a route it was
            # logging as a 404 "error" for something totally harmless.
            return "", 204

        @app.route("/")
        def index():
            return render_template("index.html", **self._lan_tip_context("/"))

        @app.route("/upload", methods=["POST"])
        def upload():
            files = request.files.getlist("files")
            if not files:
                return jsonify({"ok": False, "error": "No files received"}), 400

            # When the phone sends a whole folder, it also sends a parallel
            # "paths" list (one relative path per file, e.g. "MyFolder/a.jpg")
            # so we can rebuild the folder structure here. Plain file
            # uploads simply omit this, and every file lands flat.
            rel_paths = request.form.getlist("paths")

            dest_root = Path(self.cfg["download_folder"])
            dest_root.mkdir(parents=True, exist_ok=True)

            saved = []
            for idx, f in enumerate(files):
                if not f.filename:
                    continue
                rel = rel_paths[idx] if idx < len(rel_paths) and rel_paths[idx] else f.filename
                segments = [safe_filename(p) for p in rel.replace("\\", "/").split("/")
                            if p not in ("", ".", "..")]
                if not segments:
                    segments = [safe_filename(f.filename)]

                dest_path = dest_root.joinpath(*segments)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path = self._unique_path(dest_path)

                start = time.time()
                f.save(dest_path)  # streamed to disk by Werkzeug, handles large files
                elapsed = time.time() - start
                size_mb = dest_path.stat().st_size / (1024 * 1024)
                speed = size_mb / elapsed if elapsed > 0 else size_mb
                log.info(
                    "Received '%s' (%.2f MB) in %.2fs (%.2f MB/s) -> %s",
                    rel, size_mb, elapsed, speed, dest_path,
                )
                saved.append(str(Path(*segments)))
                self._notify_file_received(dest_path)

            return jsonify({"ok": True, "saved": saved})

        @app.route("/files")
        def list_files():
            share_dir = Path(self.cfg["share_folder"])
            share_dir.mkdir(parents=True, exist_ok=True)
            items = []
            try:
                for entry in sorted(share_dir.iterdir()):
                    if entry.is_file():
                        stat = entry.stat()
                        items.append({
                            "name": entry.name,
                            "size": stat.st_size,
                            "modified": int(stat.st_mtime),
                        })
            except OSError as exc:
                log.error("Failed listing share folder %s: %s", share_dir, exc, exc_info=True)
                return jsonify({"ok": False, "error": str(exc)}), 500
            return jsonify({"ok": True, "files": items})

        @app.route("/download/<path:filename>")
        def download(filename):
            share_dir = Path(self.cfg["share_folder"]).resolve()
            safe_name = safe_filename(filename)
            target = (share_dir / safe_name).resolve()
            # Prevent path traversal outside the share folder
            if share_dir not in target.parents and target != share_dir:
                log.warning("Blocked suspicious download request: %s", filename)
                return jsonify({"ok": False, "error": "Invalid filename"}), 400
            if not target.exists():
                return jsonify({"ok": False, "error": "File not found"}), 404
            self._log_download(target.name)
            return send_from_directory(share_dir, safe_name, as_attachment=True)

        @app.route("/text/to-laptop", methods=["POST"])
        def receive_text():
            data = request.get_json(silent=True) or {}
            text = data.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return jsonify({"ok": False, "error": "No text provided"}), 400
            entry = self.text_store.add_to_laptop(text)
            log.info("Received text from phone (%d characters)", len(text))
            return jsonify({"ok": True, "id": entry["id"]})

        @app.route("/text/to-phone")
        def text_to_phone():
            since = request.args.get("since", default=0, type=int)
            entries = self.text_store.list_to_phone(since_id=since)
            return jsonify({"ok": True, "texts": entries})

        # ------------------------------------------------------------ #
        # Shared Rooms - isolated per-visitor space for pairing a
        # stranger's own laptop + phone via the public link.
        # ------------------------------------------------------------ #
        @app.route("/room")
        def room_new():
            if not self.cfg.get("rooms_enabled"):
                return render_template("rooms_disabled.html"), 403
            room_manager.cleanup_expired(self.cfg.get("room_max_age_hours", 24))
            code = room_manager.create_room()
            return redirect(url_for("room_page", code=code))

        @app.route("/room/<code>")
        def room_page(code):
            if not self.cfg.get("rooms_enabled"):
                return render_template("rooms_disabled.html"), 403
            code = code.upper()
            if not room_manager.room_exists(code):
                return redirect(url_for("room_new"))
            room_manager.touch_room(code)
            room_url = request.host_url.rstrip("/") + url_for("room_page", code=code)
            qr_data_uri = make_qr_data_uri(room_url)
            return render_template("room.html", code=code, room_url=room_url, qr_data_uri=qr_data_uri,
                                    **self._lan_tip_context(f"/room/{code}"))

        @app.route("/room/<code>/upload", methods=["POST"])
        def room_upload(code):
            code = code.upper()
            if not self.cfg.get("rooms_enabled") or not room_manager.room_exists(code):
                return jsonify({"ok": False, "error": "Room not found or expired"}), 404

            max_mb = self.cfg.get("room_max_file_mb", 500)
            if request.content_length and request.content_length > max_mb * 1024 * 1024:
                log.warning("Room %s upload rejected: %.1f MB exceeds %d MB limit",
                            code, request.content_length / (1024 * 1024), max_mb)
                return jsonify({"ok": False, "error": f"File(s) exceed the {max_mb} MB room limit"}), 413

            files = request.files.getlist("files")
            if not files:
                return jsonify({"ok": False, "error": "No files received"}), 400
            rel_paths = request.form.getlist("paths")

            dest_root = room_manager.room_dir(code)
            dest_root.mkdir(parents=True, exist_ok=True)

            saved = []
            for idx, f in enumerate(files):
                if not f.filename:
                    continue
                rel = rel_paths[idx] if idx < len(rel_paths) and rel_paths[idx] else f.filename
                segments = [safe_filename(p) for p in rel.replace("\\", "/").split("/")
                            if p not in ("", ".", "..")]
                if not segments:
                    segments = [safe_filename(f.filename)]
                dest_path = dest_root.joinpath(*segments)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path = self._unique_path(dest_path)
                f.save(dest_path)
                log.info("Room %s: received '%s' (%.2f MB)", code, rel,
                          dest_path.stat().st_size / (1024 * 1024))
                saved.append(str(Path(*segments)))

            room_manager.touch_room(code)
            return jsonify({"ok": True, "saved": saved})

        @app.route("/room/<code>/files")
        def room_files(code):
            code = code.upper()
            if not self.cfg.get("rooms_enabled") or not room_manager.room_exists(code):
                return jsonify({"ok": False, "error": "Room not found or expired"}), 404
            room_manager.touch_room(code)
            share_dir = room_manager.room_dir(code)
            items = []
            for entry in sorted(share_dir.rglob("*")):
                if entry.is_file():
                    stat = entry.stat()
                    items.append({
                        "name": str(entry.relative_to(share_dir)),
                        "size": stat.st_size,
                        "modified": int(stat.st_mtime),
                    })
            return jsonify({"ok": True, "files": items})

        @app.route("/room/<code>/download/<path:filename>")
        def room_download(code, filename):
            code = code.upper()
            if not self.cfg.get("rooms_enabled") or not room_manager.room_exists(code):
                return jsonify({"ok": False, "error": "Room not found or expired"}), 404
            room_dir = room_manager.room_dir(code).resolve()
            target = (room_dir / filename).resolve()
            if room_dir not in target.parents and target != room_dir:
                log.warning("Room %s: blocked suspicious download request: %s", code, filename)
                return jsonify({"ok": False, "error": "Invalid filename"}), 400
            if not target.exists():
                return jsonify({"ok": False, "error": "File not found"}), 404
            room_manager.touch_room(code)
            self._log_download(target.name, prefix=f"Room {code}: ")
            return send_from_directory(room_dir, target.relative_to(room_dir), as_attachment=True)

        @app.route("/room/<code>/text", methods=["POST"])
        def room_text_post(code):
            code = code.upper()
            if not self.cfg.get("rooms_enabled") or not room_manager.room_exists(code):
                return jsonify({"ok": False, "error": "Room not found or expired"}), 404
            data = request.get_json(silent=True) or {}
            text = data.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return jsonify({"ok": False, "error": "No text provided"}), 400
            entry = room_manager.add_room_text(code, text)
            log.info("Room %s: received text (%d characters)", code, len(text))
            return jsonify({"ok": True, "id": entry["id"]})

        @app.route("/room/<code>/texts")
        def room_texts_get(code):
            code = code.upper()
            if not self.cfg.get("rooms_enabled") or not room_manager.room_exists(code):
                return jsonify({"ok": False, "error": "Room not found or expired"}), 404
            since = request.args.get("since", default=0, type=int)
            entries = [e for e in room_manager.list_room_texts(code) if e["id"] > since]
            return jsonify({"ok": True, "texts": entries})

    @staticmethod
    def _unique_path(path: Path) -> Path:
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

    def _lan_tip_context(self, path_suffix: str = "/") -> dict:
        """
        If this request came through Tailscale Funnel (i.e. over the
        internet) rather than direct LAN access, work out the local Wi-Fi
        alternative so the page can nudge the visitor toward it - same
        Wi-Fi as the laptop means no mobile data use, since the request
        never has to leave the network. X-Forwarded-Proto is only ever
        set by the reverse proxy (Funnel), never present on a direct LAN
        request, so its presence alone is a reliable signal either way.
        """
        via_tunnel = bool(request.headers.get("X-Forwarded-Proto"))
        lan_url = None
        if via_tunnel:
            ip = net_utils.get_local_ip()
            port = self.cfg.get("server_port", 8765)
            lan_url = f"http://{ip}:{port}{path_suffix}"
        return {"via_tunnel": via_tunnel, "lan_url": lan_url}

    @staticmethod
    def _log_download(name: str, prefix: str = "") -> None:
        """Log a download, noting the Range header if present. Browsers
        fetch large files (videos, APKs) using several parallel byte-range
        requests, which otherwise shows up as several near-identical
        "Sending X" lines back to back and reads like a confusing repeat
        send rather than what it actually is - one download, several
        chunks."""
        range_header = request.headers.get("Range")
        suffix = f" (range: {range_header})" if range_header else ""
        log.info("%sSending '%s' to device%s", prefix, name, suffix)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self):
        if self._running:
            log.debug("Server start requested but already running")
            return
        # waitress is a production-grade WSGI server (unlike Werkzeug's
        # built-in dev server, which prints its own "do not use in
        # production" warning) - a meaningfully better fit given this app
        # is routinely left running for days at a time.
        from waitress.server import create_server

        port = self.cfg["server_port"]
        try:
            self._httpd = create_server(self.app, host="0.0.0.0", port=port, threads=8)
        except OSError as exc:
            log.error("Failed to bind server to port %s: %s", port, exc, exc_info=True)
            raise

        self._server_thread = threading.Thread(target=self._httpd.run, daemon=True)
        self._server_thread.start()
        self._running = True
        log.info("Server started on 0.0.0.0:%s (waitress, 8 worker threads)", port)

        self._cleanup_stop_event.clear()
        self._cleanup_thread = threading.Thread(target=self._room_cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def _room_cleanup_loop(self):
        # Checks fairly often (every 5 min) since it's a cheap no-op when
        # there's nothing expired, and rooms are meant to be short-lived.
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
        self._httpd.close()  # closes the listening socket(s), which makes .run() return
        self._server_thread.join(timeout=5)
        self._running = False
        log.info("Server stopped")

    @property
    def is_running(self) -> bool:
        return self._running

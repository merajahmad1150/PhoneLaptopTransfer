# Phone <-> Laptop Transfer - Changelog

All updates to this tool are recorded here, newest at the bottom removed -
newest section is added at the END of this file each time, so the top of
the file is always the oldest history and the bottom is always current.
Dates before v1.9 are approximate, reconstructed from timestamps in
transfer.log files reviewed during those rounds of fixes, since this file
itself didn't exist yet to record them as they happened.

---

## v1.0 - Initial build (on/before Sep 7, 2026)

- Core Wi-Fi Transfer: phone <-> laptop file sharing over local Wi-Fi via
  a QR code, any file type, both directions
- ADB tab (optional): direct push/pull over USB/wireless ADB
- Auto-Sync tab (optional): Syncthing launcher
- GUI: right-click Cut/Copy/Paste/Select-All and Enter-to-next-field on
  every text field
- Everything under `D:\Tools\`, timestamped full-detail logging, crash-safe
  startup (never closes silently on error)

## v1.1 - v1.2 - Folder reorg + early bug fixes (~Sep 7-8, 2026)

- Reorganized into `core/` (all .py files), `web/` (templates + static),
  `Start.bat` at project root
- Fixed a bug where the app's data folder (config, logs, received files)
  didn't match wherever the project was actually placed, silently creating
  a second, empty-looking copy
- Replaced Werkzeug's `secure_filename` with a custom sanitizer that
  preserves Urdu/Arabic/Hindi/emoji filenames instead of stripping them
- Quieted routine 404s (e.g. `/favicon.ico`) from polluting the log at
  ERROR level with a full traceback

## v1.3 - Text sharing + whole-folder transfer (~Sep 8-11, 2026)

- Text sharing of any length, either direction, with Copy and Save-As
  (any file extension) on the laptop side
- Whole-folder drag-and-drop transfer, both directions
- Cleaned up the Wi-Fi Transfer tab, enlarged the QR code

## v1.4 - Visual overhaul (~Sep 11-12, 2026)

- Dark theme with a purple-to-teal gradient header, replacing the default
  plain-grey Tkinter look

## v1.5 - v1.7 - Screen Mirror, Public Access, Shared Rooms (~Sep 12-13, 2026)

- Screen Mirror tab: launches scrcpy (mouse control, drag-drop file push,
  clipboard sync) rather than reimplementing screen mirroring from scratch
- Public Access tab: hands off to the user's own existing Tailscale Funnel
  publisher script rather than running a second, inconsistent one
- Access PIN: optional login gate for the personal page once published
  publicly
- Shared Rooms: isolated, temporary rooms so someone else can pair their
  own laptop + phone via the public link, without touching the owner's
  personal files - auto-expiry, size caps, off by default
- Fixed a Tailscale Funnel bug where generated links used `http://`
  instead of `https://` (ProxyFix now trusts `X-Forwarded-Proto`)
- Fixed a UI bug where a tab's content (e.g. the Public Access QR code)
  could be clipped by the window with no way to scroll to it

## v1.8 - Clipboard, history controls, crash fix (~Sep 13-21, 2026)

- Fixed a clipboard-copy bug where `execCommand` could silently fail
  without the code noticing; copying now falls back through the Clipboard
  API, `execCommand`, and finally a native prompt dialog, so it can no
  longer fail with no way to get the text
- Added Clear Received Files / Clear Share Folder / Clear Text History
  buttons (previously the only way was through Windows Explorer)
- Fixed a crash where Ctrl+C in an attached console window took the app
  down via an unhandled `KeyboardInterrupt` instead of shutting down
  cleanly
- Fixed `adb_helper.list_devices()` dumping a full Python traceback into
  the log for the ordinary "adb not installed" case

---

## v1.9 - September 30, 2026

- **Switched the local server from Werkzeug's development server to
  waitress** (production-grade WSGI server) - Werkzeug's own server
  explicitly warns it isn't meant for this, and this tool is routinely
  left running for days at a time
- **Recently Received Files panel** (Wi-Fi Transfer tab): every file that
  arrives from the phone now shows up in a live list with **Show in
  Explorer** (highlights the exact file) and **Open File** buttons -
  no more digging through Explorer to find what just arrived
- **LAN-vs-internet tip banner**: if the personal page or a Shared Room is
  opened through the public Tailscale link while the visiting device is
  actually reachable on the local network, a dismissible banner now
  suggests the direct local link instead - same Wi-Fi as the laptop means
  the transfer never has to leave the network, so it can't use mobile data
- **Clearer download logging**: large files get downloaded via several
  parallel HTTP range requests (normal browser behavior), which used to
  show up as several near-identical "Sending X" log lines back to back -
  the log now shows the byte range for each one, so it reads as one
  download instead of a confusing repeat
- **Full HTTP access logging**: every request now gets one DEBUG-level
  log line (method, path, status), and waitress's own internal logger is
  now routed into the same log file, for complete transparency
- Confirmed via log review: two earlier `KeyboardInterrupt` crashes in the
  uploaded log both predate the v1.8 fix for that exact issue - not a new
  bug

# Phone <-> Laptop Transfer - Changelog

All updates to this tool are recorded here, newest at the bottom removed - newest section is
added at the END of this file each time, so the top of the file is always the oldest history and
the bottom is always current. Dates before v1.9 are approximate, reconstructed from timestamps
in transfer.log files reviewed during those rounds of fixes, since this file itself didn't exist
yet to record them as they happened.

---

## v1.0 - Initial build (on/before Sep 7, 2026)

- Core Wi-Fi Transfer: phone <-> laptop file sharing over local Wi-Fi via a QR code, any file
  type, both directions
- ADB tab (optional): direct push/pull over USB/wireless ADB
- Auto-Sync tab (optional): Syncthing launcher
- GUI: right-click Cut/Copy/Paste/Select-All and Enter-to-next-field on every text field
- Everything under `D:\Tools\`, timestamped full-detail logging, crash-safe startup (never
  closes silently on error)

## v1.1 - v1.2 - Folder reorg + early bug fixes (~Sep 7-8, 2026)

- Reorganized into `core/` (all .py files), `web/` (templates + static), `Start.bat` at project
  root
- Fixed a bug where the app's data folder (config, logs, received files) didn't match wherever
  the project was actually placed, silently creating a second, empty-looking copy
- Replaced Werkzeug's `secure_filename` with a custom sanitizer that preserves
  Urdu/Arabic/Hindi/emoji filenames instead of stripping them
- Quieted routine 404s (e.g. `/favicon.ico`) from polluting the log at ERROR level with a full
  traceback

## v1.3 - Text sharing + whole-folder transfer (~Sep 8-11, 2026)

- Text sharing of any length, either direction, with Copy and Save-As (any file extension) on
  the laptop side
- Whole-folder drag-and-drop transfer, both directions
- Cleaned up the Wi-Fi Transfer tab, enlarged the QR code

## v1.4 - Visual overhaul (~Sep 11-12, 2026)

- Dark theme with a purple-to-teal gradient header, replacing the default plain-grey Tkinter
  look

## v1.5 - v1.7 - Screen Mirror, Public Access, Shared Rooms (~Sep 12-13, 2026)

- Screen Mirror tab: launches scrcpy (mouse control, drag-drop file push, clipboard sync) rather
  than reimplementing screen mirroring from scratch
- Public Access tab: hands off to the user's own existing Tailscale Funnel publisher script
  rather than running a second, inconsistent one
- Access PIN: optional login gate for the personal page once published publicly
- Shared Rooms: isolated, temporary rooms so someone else can pair their own laptop + phone via
  the public link, without touching the owner's personal files - auto-expiry, size caps, off by
  default
- Fixed a Tailscale Funnel bug where generated links used `http://` instead of `https://`
  (ProxyFix now trusts `X-Forwarded-Proto`)
- Fixed a UI bug where a tab's content (e.g. the Public Access QR code) could be clipped by the
  window with no way to scroll to it

## v1.8 - Clipboard, history controls, crash fix (~Sep 13-21, 2026)

- Fixed a clipboard-copy bug where `execCommand` could silently fail without the code noticing;
  copying now falls back through the Clipboard API, `execCommand`, and finally a native prompt
  dialog, so it can no longer fail with no way to get the text
- Added Clear Received Files / Clear Share Folder / Clear Text History buttons (previously the
  only way was through Windows Explorer)
- Fixed a crash where Ctrl+C in an attached console window took the app down via an unhandled
  `KeyboardInterrupt` instead of shutting down cleanly
- Fixed `adb_helper.list_devices()` dumping a full Python traceback into the log for the
  ordinary "adb not installed" case

---

## v1.9 - September 30, 2026

- **Switched the local server from Werkzeug's development server to waitress** (production-grade
  WSGI server) - Werkzeug's own server explicitly warns it isn't meant for this, and this tool
  is routinely left running for days at a time
- **Recently Received Files panel** (Wi-Fi Transfer tab): every file that arrives from the phone
  now shows up in a live list with **Show in Explorer** (highlights the exact file) and **Open
  File** buttons - no more digging through Explorer to find what just arrived
- **LAN-vs-internet tip banner**: if the personal page or a Shared Room is opened through the
  public Tailscale link while the visiting device is actually reachable on the local network, a
  dismissible banner now suggests the direct local link instead - same Wi-Fi as the laptop means
  the transfer never has to leave the network, so it can't use mobile data
- **Clearer download logging**: large files get downloaded via several parallel HTTP range
  requests (normal browser behavior), which used to show up as several near-identical "Sending
  X" log lines back to back - the log now shows the byte range for each one, so it reads as one
  download instead of a confusing repeat
- **Full HTTP access logging**: every request now gets one DEBUG-level log line (method, path,
  status), and waitress's own internal logger is now routed into the same log file, for complete
  transparency
- Confirmed via log review: two earlier `KeyboardInterrupt` crashes in the uploaded log both
  predate the v1.8 fix for that exact issue - not a new bug


---

## v2.0 - October 11, 2026

Big upgrade built from a full review of the code and of the logs (including the Oct 1 `No module
named 'waitress'` crashes and the Oct 10 "Application not found" error when opening a PDF).
**Replace the whole project folder, but keep your own `config.json`** (new settings are added to
it automatically; nothing is lost).

**New features**
- **Logo** (gradient phone + laptop with two-way arrows): window title bar/taskbar, gradient
  header, start-up dialog, every web page (header, favicon, phone home-screen icon), Desktop
  shortcut. Files: `assets/logo.ico/png`, `web/static/logo.*`, generator `assets/make_logo.py`.
- **Console window title** now reads "Phone-Laptop Transfer v2.0 - Console / Live Log ..." (set
  by `Start.bat` and again by Python).
- **One log file per session**: `logs/sessions/session_YYYY-MM-DD_HH-MM-SS.log`, with a header
  (versions, paths, disk space, encoding) and a footer (duration, counts per level, transfer
  statistics, clean/crash verdict). `logs/latest_session.txt` points to the newest. A
  crash/force-close is detected at the next start ("previous session did not end cleanly"). Old
  `transfer.log*` files are moved to `logs/archive_old/`.
- **Log noise removed**: identical consecutive lines are collapsed into one line + "repeated N
  more times"; polling requests, static files and per-range download lines no longer flood the
  log; the LAN-IP line is logged only when it changes. Nothing important is hidden: errors are
  never collapsed, unhandled errors in ANY thread, Tk callbacks and hard crashes (faulthandler)
  are all captured.
- **Auto-copy to clipboard**: text sent from the phone over the local Wi-Fi is copied to the
  laptop clipboard instantly (Unicode-safe, Urdu intact). Never for internet/tunnel visitors
  (Settings toggle).
- **Frontend history expiry**: items vanish from the phone page after `frontend_visible_hours`
  (default 6, Settings) but stay on the laptop: `data/history.jsonl` (everything),
  `ReceivedText/texts_YYYY-MM-DD.txt` (readable texts), `ReceivedFromPhone/`, `ShareToPhone/`.
- **Public link is automatic**: the tool asks the local Tailscale client what is being published
  for its port (`serve status --json`, text fallback) and shows the live URL + QR by itself,
  re-checking every 10 s. No pasting, no "Show QR" button. Optional manual fallback link in
  Advanced.
- **Start-up choice**: desktop window (GUI) or web control panel (`/admin`, local network only)
  - can be remembered; `--mode gui|web` on the command line. If Tk cannot start, the tool falls
  back to web mode by itself.
- **Web control panel** (`/admin`): status, QR codes, everything shared (with downloads of
  received files), send text/files to the phone, live log, clear history, quit.
- **Screen Mirror page**: Android over USB, **Android wireless by scanning a QR code** (Wireless
  debugging > Pair device with QR code), connect-by-address for phones on other networks (e.g.
  Tailscale IP), and an optional **iPhone AirPlay** receiver launcher. See README for the honest
  limits.
- **Coloured-icon sidebar** replaces the 8 cramped tabs; multi-colour gradient header; per-page
  coloured icons drawn in code.
- **Keyboard/mouse**: right-click pastes immediately (only replaces a selection;
  Shift+right-click for the full menu), Ctrl+A works everywhere, Enter = next field, Ctrl+1..8
  pages, F5, Ctrl+O, Ctrl+Shift+O, Ctrl+E, Ctrl+Shift+C, Ctrl+Enter, Ctrl+L, F1, Ctrl+Q.
  Mouse-wheel scrolling now works over any widget.
- **Open-file fallback**: if Windows has no program for a file type (the Oct 10 PDF error), the
  "Open with" chooser appears.
- **Start.bat does the setup**: finds/creates `.venv` with uv, installs/updates packages every
  start, keeps uv's cache and Python under the project folder (D:), never closes on error.
- **Desktop shortcut** script (`Create_Desktop_Shortcut.bat`) with the logo.

**Speed**
- Phone page uploads **one raw request per file** (no multipart parsing on the i3), **3 files in
  parallel**, with per-file progress + MB/s and automatic retry.
- waitress tuned: 256 KB socket buffers (default was 8 KB), uploads up to 128 MB stay in RAM (no
  temp-file copy), 1 GB request cap removed, larger uploads spill to `temp/` on D: (not C:).
- Folder zips store already-compressed files (photos, video, PDF, zip...) instead of
  recompressing them.
- Honest speed numbers: the old log's "300-400 MB/s" only measured copying a temp file; the new
  log reports the real transfer speed measured by the phone page.

**Fixes (from the review)**
- Missing packages are installed automatically; a clear message replaces the old
  `ModuleNotFoundError` crash.
- The access PIN is no longer written to the log; PIN check is constant-time, **5 wrong tries
  lock the visitor out** (growing delay); `next=` redirect validated; XHR calls get a JSON 401
  instead of a login page (the phone used to show "Sent" when the session had expired).
- Shared Rooms: text ids no longer repeat after 100 texts (phones stopped receiving); per-room
  total size cap, max rooms, text size cap, per-IP room-creation rate limit, leftover room
  folders purged at start, everything under a lock.
- Free-space check before accepting an upload (HTTP 507 with a clear message); uploads written
  to `*.part` and renamed only when complete; empty files work.
- scrcpy: output is now read (it could eventually freeze), uses the same adb as the tool,
  processes are closed on exit; ADB: UTF-8 decoding, unauthorized/offline phones are explained,
  pull creates the destination folder even if its name contains a dot.
- Server start failure (port busy) now shows a clear message instead of "Something went wrong".
- Live log panel is capped (2,000 lines) and fed through a queue (thread-safe).
- Phone pages: `dir="auto"` so Urdu/Arabic text displays right-to-left correctly.
- `qrcode` 8.x now supported (requirement was `<8.0`).
- Removed `install.ps1` (it installed to `C:\Users\...\Tools` with pip, against your D:/uv
  rules).

**Tests added** (`tests/`): 55 server checks, GUI smoke test (headless fakes), end-to-end HTTP
test. Not testable here and therefore still needing your confirmation: the real Windows GUI
look, real waitress/qrcode, Tailscale detection against your real publisher, clipboard API, ADB
QR pairing. **Please send the session log after your first run.**


---

## v2.0.1 - October 11, 2026

- `.gitignore` updated so `git add .` can no longer publish personal data created by v2.0:
  `data/` (history of your texts and file names), `ReceivedText/`, `temp/`, `.uv/`,
  `config.json.tmp`, `*.part`. Already ignored: `config.json` (contains your PIN and paths),
  `logs/`, `ReceivedFromPhone/`, `ShareToPhone/`, `rooms/`, `.venv/`.


---

## v2.0.2 - October 13, 2026

From your attached session log (23:57 session) and screenshot. Files changed: see "Where to put
them" in the reply.

- **Bigger QR codes**: 360 px on the Wi-Fi Transfer and Public Access pages, 340 px for the
  Android pairing QR, 320 px on the room page, 260 px in the web control panel. They are now
  scaled by whole-number factors with no blurring (the old resize blurred the modules), so they
  scan faster and from further away.
- **Easier to read web page**: lighter hint/grey text, larger hint and button text, slightly
  larger text and a wider column on desktop browsers. (If specific words are still missing on
  your screen, tell me which.)
- **Log: room QR link used `http://` + `:8443`**, which can never work. Links made while the
  page is opened through the public name now use the real `https://` public URL.
- **Log: public-name requests looked local** (`from 127.0.0.1 [local]`): requests that arrive
  using the `*.ts.net` / published host name are now treated as internet requests even if no
  proxy headers are present, so they are never auto-copied and `/admin` is refused for them.
- **Text typed on the laptop itself no longer overwrites the clipboard** (log: 1005 chars from
  127.0.0.1 were auto-copied); only other devices on your Wi-Fi trigger auto-copy.
- **Unclean-exit marker**: closing the console window (X), logging off or shutting down now
  stops the server and writes the session footer first, so the next start no longer warns
  "previous session did not end cleanly" after a normal close.
- **Log: ambiguous "previous line repeated" marker** replaced by "the line above repeated N more
  time(s), last at HH:MM:SS: <text>".
- **Log tidy-ups**: Tailscale "detection note" only when nothing is found; tiny uploads no
  longer show "0.00s = 0 MB/s".
- **Internet scanner defence**: bots probe public links for `.env`, `.git/config`, `*.php`.
  After 15 invalid requests in a minute an address is refused for 10 minutes (one warning line
  instead of hundreds), local devices are never blocked. A warning is logged when your public
  link is live without an access PIN.
- Version 2.0.2; the Start.bat console title no longer repeats the version number.


---

## v2.1.0 - October 18, 2026

From your 9 session logs + adb.log + history.jsonl and your 5 requests.

**Your requests**
1. **Time stamps everywhere**: desktop window - "Received from phone" and new "Sent to phone"
   lists (date + time), Text page (received and sent texts, date + time); phone page - every
   file ("sent 14 Oct 2026, 19:10:32"), every text ("From laptop - ..."), every finished upload
   ("Sent ..."), plus sent/failed times in status lines. Shown in the viewer's own time zone.
2. **Clear text on the phone**: the desktop "Clear" now also clears the phone page's "Text from
   laptop" (before it only hid the laptop-side list, so the phone kept showing everything). The
   phone page has **Clear** buttons for texts and for the file list; other devices on the page
   update within ~20 s. Saved data stays on the laptop. (Per-scope clear markers in
   `data/history.jsonl`; old markers still understood.)
3. **Mirror quality = Maximum by default**: native resolution (no `--max-size`), 40 Mbps, 60
   fps; applied once to existing configs. Preset list (Maximum / High / Balanced / Low
   bandwidth). The log showed your tests were really applied (`--max-size 1200 --video-bit-rate
   16M --max-fps 60`) - 1200 px on a 2400x1080 phone is only half the pixels, which is why it
   still looked poor.
4. **Laptop -> phone apps**: new *Send files to the phone gallery* (Screen Mirror page, Ctrl+G):
   adb push into `/sdcard/DCIM/PLT` (photos/videos/audio, then Android is asked to index them so
   Instagram/Gallery pickers list them) or `/sdcard/Download/PLT` (documents); recorded in
   history with a time stamp. Dragging files onto the mirror window now lands in the same
   gallery folder (`--push-target`) and triggers the same indexing. **Clipboard**: the page
   explains exactly how scrcpy paste works (click the window, Ctrl+V / Alt+Shift+V; the phone's
   own long-press Paste uses the phone clipboard) and a new button sends the Windows clipboard
   to the phone page for any language. The log shows phone->Windows clipboard works ("Device
   clipboard copied"); Windows->phone needs the paste done inside the mirror window - please try
   and send the next log.
5. **Log review** - see below.

**Fixed from the logs**
- **Crash on Ctrl+C** (session 10-14 and 10-18: `KeyboardInterrupt` in `mainloop`, "FATAL
  ERROR"): Ctrl+C in the console now asks "Quit?" instead; if it ever reaches the main loop the
  window closes cleanly.
- **Crash at start-up with a blank `startup_mode`** (session 10-12 23:06: `'NoneType' has no
  attribute 'deiconify'`): invalid values are repaired to "ask" in the config, at start-up and
  when saving Settings.
- **waitress `WinError 10038 ... not a socket` errors on every quit in web mode**: harmless but
  logged as ERROR; now a single quiet line.
- **Duplicate history entries** (ids 29 and 30 were the same APK): files are copied to `*.part`
  and renamed when complete (the phone can no longer be offered a half-copied file), and a file
  registered twice within seconds is recorded once.
- **Large downloads gave only "Client disconnected"** (APK 109 MB x3, zip 415 MB): the log now
  says "Finished sending ... MB in s = MB/s" or "STOPPED EARLY: x of y MB after s - the phone
  cancelled, paused or lost Wi-Fi".
- **QR pairing found nothing** (`mDNS services seen: []` for the whole attempt): the tool now
  checks `adb mdns check` first and says clearly when this adb has no mDNS; new **Pair with a
  code** (ip:port + 6-digit code) fallback.
- **scrcpy exit is now logged with its exit code and last output** (adb.log showed two
  "connection terminated: read failed" - the USB phone disconnected; the app said nothing).
- Tailscale detection notes are one line instead of a pretty-printed JSON block.
- Version 2.1.0.

**Tests**: 72 server checks (new: clear scopes, timestamps, dedupe, `.part`, download timing,
config migration, scrcpy flags, gallery push), GUI smoke test, end-to-end test. Still needs your
confirmation on Windows: gallery indexing on your Xiaomi (HyperOS may need "USB debugging
(Security settings)" ON), clipboard paste behaviour, mDNS check output.


---

## v2.2.0 - November 23, 2026

From your six session logs (Nov 1 - Nov 21) and your new requests.

### Your requests

**1. Drag and drop from the laptop to the phone.** Drop files or folders anywhere on the window
(or on the new drop zone on the Wi-Fi Transfer page) and they are offered to the phone; folders
are zipped first. On the Screen Mirror page a drop goes into the phone gallery over ADB; on the
ADB page it fills the file box; dropped text goes to the phone page. Uses the small
`tkinterdnd2` package, which `Start.bat` installs. If it is missing the tool says so in the log
and everything else still works.

**2. Paste a screenshot, it goes to the phone.** Take a screenshot with Win+Shift+S, then press
Ctrl+V in the tool (outside a text box) or Ctrl+Shift+V (anywhere). It is saved as
`screenshot_DATE_TIME.png` in the share folder and appears on the phone page. Files you copied
in Explorer are sent the same way.

**3. Requirements list.** Every point of your latest list was checked - see "Requirement check"
below.

**4. Log review.** See "Fixed from the logs".

**5. Text from the internet link is copied too.** New setting *Auto-copy phone text from:
everywhere / wifi / off* (default **everywhere**). Text typed on the laptop itself never
overwrites the clipboard. With no access PIN anyone holding your public link could replace your
clipboard, so the log warns once when this happens.

### Additional feature: Clip Shelf

A small borderless window that stays on top of every other window and holds the things you
reuse: captions, hashtags, comment replies, documents, pictures, videos, mp3, PDFs.

**Use it.** Double-click an item: it is copied and pasted into the app you were typing in (the
shelf never takes keyboard focus unless you ask). Drag an item out into any program, or drag
text/files in from anywhere.

**Organise it.** Edit, rename, delete, move to top / middle / bottom / up / down (right-click or
Alt+Up/Alt+Down), search with `/`. Win+Shift+S pictures, copied files and text can be saved with
the **+** button or the hotkey.

**Move and hide it.** Drag the top strip to move, the corner grip to resize, **-** collapses it
to a thin tab on the screen edge, Ctrl+Alt+V shows/hides it from anywhere, Ctrl+Alt+C saves the
clipboard into it. Opacity, text size, always-on-top and focus behaviour are in its menu.

**Light on memory.** It lives inside the tool (no extra program) and keeps only short records in
memory - pictures and thumbnails are never loaded. `Start_Shelf.bat` runs the shelf alone
without the web server for the lowest RAM. Memory use is written to the log at start, every 10
minutes and at exit, so the "minimal RAM" goal can be checked.

### Added from the requirement list

**Settings gear in the top right** opens Settings: paths, behaviour, header colour themes
(Aurora, Sunset, Ocean, Forest, Berry, Midnight), show/hide sidebar pages, hide or show the log
panel, text size, shelf options.

**Hover explanations** on buttons, sidebar pages, the logo and the gear.

**Log highlighting**: routine lines are dim, important lines (received, sent, finished, live,
statistics...) are bright, warnings yellow, errors red - in the log panel and in the console
window.

**Time stamps on every status line** in the window, not only in the log.

**Self-test (simulates a phone)**: one button uploads, sends text, downloads and checks the
clipboard on this laptop, shows each step with a time stamp and real speed, then removes its
test files.

**Notes layout**: this file, README and SETUP are now wrapped to about 96 characters so they
never need horizontal scrolling; headings and key words are bold.

### Fixed from the logs

**Public link flipped to "not published" about every hour.** The Tailscale commands sometimes
took longer than 8 seconds and a timeout was read as "nothing published", then 15 s later the
link came back. Timeouts now keep the last known link, the wait is 20 s, only one command is run
when it answers, and polling relaxes to every 30 s once the link is live (fewer processes on
your i3).

**Every start said "previous session did not end cleanly".** The tool is usually ended by
shutting down or restarting the computer, which gives a program no chance to write its footer. A
"still alive" time is now saved every 30 s; the next start adds a recovery note to the old log
("last sign of life: ...") and the warning explains the likely cause.

**A 57-second page load and a 7-second text delivery.** The computer was almost certainly asleep
or frozen. A watchdog now logs "the computer was asleep or locked for N seconds", slow responses
(over 3 s) are logged as warnings, and clipboard copy time is logged.

**Slow first start (14-18 seconds after a reboot).** Start-up now logs the time spent on config,
packages, server and window, and `Start.bat` precompiles packages (`UV_COMPILE_BYTECODE`). Send
the next log to see where the time goes.

**"No default program" for PDF files.** Files with no associated program (PDF, pictures, text,
media) now open in your web browser first; the "Open with" chooser appears only if that fails.

**Internet visitors all appear as 127.0.0.1.** The Tailscale link does not pass the visitor's
address. The log now records once which headers arrive so a real address can be found.

### Requirement check

Done and kept: uv for the environment, waitress, qrcode 8, everything under
`D:\Tools\PhoneLaptopTransfer`, real progress with time stamps, full logs (one file per run,
highlighted), GUI first, right-click paste, Enter-to-next, shortcuts, start-up choice with
"Remember my choice", scrollable pages, drag and drop, Settings gear top right, hover help,
logo, ASCII-only names for files the tool creates, changelog in one file, changed-files zip plus
full zip.

Not needed here, so not added: transcription/translation/AI (no Gemini key is needed by this
tool), QSV (no CSV work), video frame stepping, Urdu punctuation models. If you want captions in
the shelf converted to Roman Urdu or punctuated, that is the natural place to add the Gemini key
option.

### Tests

**New:** 22 logic checks (shelf, hotkeys, log highlighting, Tailscale handling, recovery
footer), 4 more server checks, a self-test simulation, and the window smoke test now exercises
the shelf, drops and screenshot paste. **Still needs your PC:** the real look of the shelf, drag
and drop (needs `tkinterdnd2` installed by `Start.bat`), global hotkeys, no-focus-steal pasting,
clipboard files/pictures. Please send the next log after trying them.

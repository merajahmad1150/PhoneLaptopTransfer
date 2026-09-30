# Phone ↔ Laptop Transfer

A Windows GUI app for moving files, whole folders, and text between your
Android phone and laptop with one click — over local Wi-Fi, or from
anywhere in the world via an optional public URL. Includes full
mouse-controlled screen mirroring of the phone too.

## Features

- **Wi-Fi Transfer (main feature)** — start a local web server from the
  GUI, scan the (large) QR code with your phone, and you get a page with
  a drag-and-drop upload zone (phone → laptop, files AND whole folders)
  and a file list you can tap to download (laptop → phone). Works with
  any phone browser, no app install needed on the phone. On the laptop
  side, **Add Files to Send to Phone...** / **Add Folder to Send to
  Phone...** make anything instantly available for the phone to pull.
- **Text (any length, either direction)** — a dedicated Text tab on the
  laptop and a text box on the phone page. Whatever's sent shows up with
  a **Copy** button and a **Save As...** dialog that lets you browse to
  any location and save as `.txt`, `.py`, `.bat`, or literally any
  extension you type. No length limit.
- **Whole-folder transfer, either direction** — drag a folder onto the
  phone page (desktop browsers) or use "choose a whole folder" (works on
  most Android browsers too) to send a folder to the laptop with its
  structure intact. Going the other way, "Add Folder to Send to
  Phone..." zips it up so your phone can download it as one file.
- **Screen Mirror (optional)** — mirror the phone's screen on the laptop
  and control it with the mouse: open apps, tap, swipe, and use a file
  manager app on the phone (through the mirror) to move/copy/delete
  things. Also supports drag-and-drop of a file straight onto the mirror
  window to push it to the phone, and clipboard sync between PC and
  phone. Built on **scrcpy**, a free, open-source, actively-maintained
  tool made exactly for this — see "Why scrcpy" below for why this app
  launches it rather than reimplementing screen mirroring from scratch.
- **Public Access (optional)** — publish the Wi-Fi Transfer server to
  the internet via **your existing Tailscale Funnel publisher script**
  (this app hands off to it rather than running its own separate
  publishing logic, so every tool you publish stays consistent). Includes
  an **Access PIN** you can turn on so publishing publicly doesn't mean
  leaving the door open with no lock.
- **Shared Rooms (optional)** — let someone else use this tool between
  their OWN laptop and phone, entirely separate from your personal
  files. Share the `/room` link (local or public); each visitor gets
  their own isolated room with a QR code to pair their second device,
  their own file list, and their own text feed — invisible to you and
  to every other visitor. Off by default, with a per-room size cap and
  automatic expiry since it means letting strangers use your PC's
  storage temporarily.
- **ADB (optional)** — if your phone is plugged in via USB (or set up
  for wireless ADB) and you have Android platform-tools installed, this
  tab pushes/pulls files directly, which is faster for large batches.
- **Auto-Sync (optional)** — a launcher/shortcut for Syncthing, a free
  separate tool that keeps folders continuously synced in the background
  once paired, so you don't have to transfer manually at all.
- Filenames are preserved exactly as-is, including Urdu/Arabic/Hindi
  script — only characters Windows actually forbids get sanitized, so
  nothing gets silently mangled or lost.
- A dark theme with a purple-to-teal gradient header, instead of the
  plain default grey.
- Real-time, timestamped logs shown in the app and written to a log file,
  so if something goes wrong you can see exactly what happened — the
  app never just closes silently on an error.
- Everything configurable from the Settings tab: server port, which
  folders are used for uploads/downloads, and tool paths.

## Why scrcpy instead of a custom-built mirror

Screen mirroring with real mouse control means capturing the phone's
video feed, decoding H.264 in real time, and translating mouse clicks
back into touch events on the device — a large, failure-prone project to
get right from a standing start. scrcpy already does this well, is
open-source, and is maintained by people who specialize in exactly this
problem. This app launches it with sensible defaults rather than
reinventing it — the more honest and reliable engineering choice.

## A note on public access and security

Once published via your Tailscale Funnel publisher, the URL is reachable
by anyone who has it — there's no login unless you turn on the **Access
PIN** in the Public Access tab. Tailscale Funnel URLs aren't publicly
listed anywhere, but treat the URL itself like a password: don't post it
anywhere public, and turn the PIN on if you're sharing it with anyone
besides yourself.

## How Shared Rooms work

The Access PIN above protects your *personal* page (`/`) — your own
files, your own text history. Shared Rooms is a deliberately separate,
lower-stakes area at `/room` for when you actually *want* someone else
to use the tool:

- Visiting `<link>/room` always creates a **brand-new, isolated room**
  and redirects to it (`/room/<code>`) — two different people opening
  the same base link never land in the same room.
- That room page shows a QR code for its own URL, so the person can pair
  their second device (e.g. their phone) to the *same* room.
- Files and text added in a room are visible only within that room —
  not to you, and not to anyone in a different room.
- Rooms are **not** protected by your Access PIN (that would defeat the
  point of handing out a room link) and are **off by default** — you
  turn them on in the Shared Rooms tab.
- Each room auto-deletes after a period of inactivity (24 hours by
  default), and uploads are capped in size (500 MB by default) — both
  adjustable in the Shared Rooms tab. Rooms also don't survive an app
  restart.
- Since this uses your PC's own disk and bandwidth, only enable it while
  you actually intend for someone else to be using it.

## A note on whole-folder transfer from the phone

Real folder drag-and-drop is a desktop browser feature. On Android,
"choose a whole folder" opens the system file picker in folder-select
mode, which works on most phones/browsers but depends on your Android
version and file manager — if it doesn't offer a folder option, the most
reliable fallback is zipping the folder on your phone first (most
Android file managers can do this) and sending the zip as a regular
file.

## Folder structure

```
phone-laptop-transfer/
├── Start.bat                  # Double-click this to run the app
├── requirements.txt
├── README.md
├── SETUP_GUIDE.md
├── core/                       # All .py files live here
│   ├── run.py                    # Entry point
│   ├── config.py                 # Settings load/save (config.json)
│   ├── logger.py                 # Timestamped logging (file + console + GUI)
│   ├── net_utils.py               # Finds your laptop's LAN IP
│   ├── qr_helper.py               # Generates QR codes
│   ├── web_server.py              # The Flask server (core Wi-Fi transfer + PIN gate)
│   ├── adb_helper.py              # Optional ADB push/pull
│   ├── syncthing_helper.py        # Optional Syncthing launcher
│   ├── scrcpy_helper.py           # Optional screen-mirror launcher (scrcpy)
│   ├── safe_names.py              # Windows-safe filenames that preserve Urdu/Unicode
│   ├── text_store.py              # Shared in-memory store for two-way text sharing
│   ├── room_manager.py            # Isolated per-visitor rooms for Shared Rooms
│   ├── theme.py                   # Dark theme + gradient header styling
│   ├── ui_helpers.py              # Right-click menus + Enter-to-next-field
│   └── main_window.py             # The Tkinter window (all tabs)
└── web/                        # Everything the phone's browser loads
    ├── templates/
    │   ├── index.html               # The page your phone opens
    │   ├── unlock.html               # PIN entry page (only shown if PIN is on)
    │   ├── room.html                  # Shared Room page (own QR, files, text)
    │   └── rooms_disabled.html        # Shown if someone visits /room while it's off
    └── static/                   # CSS + JS for those pages
```

This app deliberately does NOT include its own Tailscale-calling script -
the Public Access tab hands off to your existing
`D:\Tools\tailscale-publisher\PUBLISH-TOOL.bat` instead, so every tool
you publish goes through the same already-working script (see
SETUP_GUIDE.md).

Logs are written to `logs\transfer.log` inside the project folder
(created automatically). The app's config file and the default
upload/share folders also live right inside the project folder itself,
wherever you placed it (e.g. under `D:\Tools\`) — nothing is created
anywhere else.

## Quick start

See `SETUP_GUIDE.md` for full step-by-step instructions. Short version:

```
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
```

Then just double-click **Start.bat** any time you want to run the app
(it activates the venv and launches `core\run.py` for you).

Click **Start Server** on the Wi-Fi Transfer tab and scan the QR code
with your phone.

## GUI usability

Every text field supports right-click Cut/Copy/Paste/Select All, and
pressing Enter moves to the next field. Standard Ctrl+C/X/V shortcuts
work throughout, courtesy of `core/ui_helpers.py`.

## Suggested advancements

A few ideas worth considering later, based on how similar tools
(LocalSend, Snapdrop) handle this problem:

- **Auto-discovery** — LocalSend uses a UDP broadcast so paired devices
  find each other automatically without re-scanning a QR code every
  session. Could add this so the phone remembers the laptop and
  reconnects on its own next time you're on the same Wi-Fi.
- **Resumable uploads** — for large Urdu video files, a chunked upload
  that can resume after a dropped Wi-Fi connection instead of restarting
  from zero.
- **"Add to Home Screen"** — making the phone page a installable PWA so
  it behaves like a real app icon on the phone instead of a browser tab.
- **Desktop notification on transfer complete** — a Windows toast when
  a file finishes uploading, useful if you've alt-tabbed away.
- **System tray minimize** — keep the server running in the tray instead
  of needing the window open, so it doesn't get in the way while editing.

None of these are built yet — happy to add any of them if useful.

## Updating later

If you ask for a small fix or feature change later, you'll be given just
the changed file(s) with instructions on which existing file to overwrite
— not a full re-zip of the whole project.

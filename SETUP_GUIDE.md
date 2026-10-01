# Setup Guide

## 1. Unzip the project

Unzip this project somewhere under `D:\Tools\`, e.g.:

```
D:\Tools\phone-laptop-transfer\
```

Everything the app needs or creates — its config file, logs, and the
default upload/share folders — lives right inside this same folder,
wherever you put it. Nothing gets created anywhere else.

> **If you used the previous version:** it had a bug where it created a
> separate `D:\Tools\PhoneLaptopTransfer\` folder for its data regardless
> of where you'd actually unzipped the app. That's fixed now. If you have
> an old `D:\Tools\PhoneLaptopTransfer\` folder from before, any files you
> received are in its `ReceivedFromPhone` subfolder — move them into
> the new project folder's `ReceivedFromPhone` folder, then you can delete
> the old stray folder.

## 2. Create the virtual environment with uv

Open a terminal (PowerShell or Git Bash) in the project folder:

```
cd D:\Tools\phone-laptop-transfer
uv venv
```

Activate it:

- PowerShell: `.venv\Scripts\Activate.ps1`
- CMD: `.venv\Scripts\activate.bat`
- Git Bash: `source .venv/Scripts/activate`

## 3. Install dependencies

```
uv pip install -r requirements.txt
```

Tkinter (used for the GUI) ships with the standard Windows Python
installer, so it doesn't need a separate pip install. If you installed
Python from python.org and unchecked "tcl/tk" during setup, re-run the
installer and make sure that option is checked.

## 4. Run the app

From now on, just double-click **`Start.bat`** in the project folder —
it activates the virtual environment and launches the app for you.

(If you prefer the terminal: `python core\run.py` with the venv active.)

A window titled "Phone ↔ Laptop Transfer" should open with four tabs.

## 5. First-time Windows Firewall prompt

The first time you click **Start Server**, Windows may show a firewall
prompt asking whether to allow Python to accept connections on private
networks. Click **Allow** — this is required for your phone to reach the
server. If you accidentally click "Deny," you can fix it later in
**Windows Security → Firewall & network protection → Allow an app**.

## 6. Connect from your phone

1. Make sure your phone is on the **same Wi-Fi network** as your laptop.
2. On the laptop, go to the **Wi-Fi Transfer** tab and click **Start Server**.
3. A QR code appears — scan it with your phone's camera, or type the
   URL shown into your phone's browser.
4. On the phone page:
   - Drag/tap files into the top box to send them **to** your laptop.
     Whole folders work too (drag one from a desktop browser, or use
     "choose a whole folder" on the phone).
   - Tap **Get** next to any file in the bottom list to download it **to**
     your phone.
   - Type or paste any amount of text under "Send text to laptop" and
     tap **Send to Laptop**.
   - Whatever the laptop sends you shows up under "Text from laptop" —
     tap **Copy** or **Download** there.

**Sending laptop → phone:**
- Files: click **Add Files to Send to Phone...** on the Wi-Fi Transfer
  tab, pick any files, and they're instantly available for your phone to
  download (tap Refresh on the phone page to see them). **Open Share
  Folder** is there too if you'd rather drag files in via Explorer.
- Whole folders: click **Add Folder to Send to Phone...**, pick a
  folder — it gets zipped in the background and shows up as one
  downloadable `.zip` on the phone page once ready.
- Text: go to the **Text** tab, type into "Send text to phone", and
  click **Send to Phone**.

**Text received from the phone** shows up live in the **Text** tab's
list (newest first). Click an entry to preview it, then **Copy** it or
**Save As...** to write it to any file type you want, anywhere on disk
(the Save dialog lets you type any extension, not just the ones listed).

Files sent from the phone land in the folder configured as "Download
folder" in the **Settings** tab (default: `ReceivedFromPhone`, inside
the project folder, with subfolders preserved for whole-folder
transfers). Files you add for the phone go into the "Share folder"
(default: `ShareToPhone`).

**Finding a file you just received**: no need to open Explorer — the
Wi-Fi Transfer tab's **Recently Received Files** list shows everything as
it arrives. Double-click an entry (or select it and click **Open File**)
to open it with its default app, or click **Show in Explorer** to jump
straight to it, already selected, in a File Explorer window.

**If you ever see a banner** on the phone/room page suggesting a local
link instead — that means the page was opened through the public
internet link rather than directly over Wi-Fi. Tapping the suggested
link switches to a connection that stays entirely on your own network
(see "Local Wi-Fi vs the internet" in README.md for why this can't be
done automatically).

## 7. Optional: ADB tab (faster wired transfer)

Only needed if you want direct USB transfer instead of/alongside Wi-Fi.

1. Download **Android platform-tools** from Google:
   `https://developer.android.com/tools/releases/platform-tools`
2. Unzip it to, e.g., `D:\Tools\platform-tools\`.
3. Add that folder to your Windows PATH, **or** just enter the full path
   to `adb.exe` in the Settings tab's "ADB path" field
   (e.g. `D:\Tools\platform-tools\adb.exe`).
4. On your phone: **Settings → About phone → tap "Build number" 7
   times** to enable Developer Options, then **Settings → Developer
   options → enable USB debugging**.
5. Plug your phone in via USB, tap "Allow" on the phone when prompted to
   trust the computer.
6. In the app's **ADB tab**, click **Check ADB** then **List Devices** to
   confirm it sees your phone, then use the Push/Pull sections.

## 8. Optional: Auto-Sync tab (Syncthing)

Only needed if you want folders to sync automatically in the background,
with no manual transfer step at all.

1. Install Syncthing on your laptop: `https://syncthing.net/downloads/`
2. Install the Syncthing app on your Android phone (Google Play or
   F-Droid).
3. In this app's **Auto-Sync tab**, click **Launch Syncthing** then
   **Open Web UI** to reach Syncthing's own setup screen.
4. Follow Syncthing's own pairing steps (it will show a QR code / device
   ID on each side) — this is a one-time setup done entirely inside
   Syncthing's interface, not this app.
5. Once paired, any folder you add to the sync in Syncthing keeps itself
   updated on both devices automatically.

## 9. Optional: Screen Mirror tab (control your phone with the mouse)

Lets you see and control your phone from the laptop — open apps, and use
a file manager app on the phone (through the mirror) to move, copy, or
delete things with clicks instead of touches. Built on **scrcpy**, a
free, open-source, actively-maintained tool made exactly for this,
rather than this app trying to reimplement screen mirroring itself.

1. Download scrcpy (Windows build) from:
   `https://github.com/Genymobile/scrcpy/releases`
2. Unzip the whole folder to, e.g., `D:\Tools\scrcpy\`.
3. Add that folder to your Windows PATH, **or** enter the full path to
   `scrcpy.exe` in the Settings tab's "scrcpy path" field
   (e.g. `D:\Tools\scrcpy\scrcpy.exe`).
4. Make sure ADB is set up too (step 7 above) and your phone is
   connected via USB (or wireless ADB) with debugging enabled.
5. In the app's **Screen Mirror tab**, click **Check scrcpy** and
   **Check ADB** to confirm both are found, then **Start Mirroring**.
6. Once the mirror window opens: click/drag with your mouse like it's a
   touchscreen. Drag a file (or an `.apk`) straight onto the window to
   send it to the phone. Copy/paste syncs between your PC and phone
   clipboards automatically.

The default performance settings (max size 800px, 4 Mbps, 30 fps) are
tuned conservatively for older/integrated graphics rather than maximum
sharpness — raise them in the Screen Mirror tab if your hardware handles
it comfortably and you want a crisper picture.

## 10. Optional: Public Access (use it from anywhere in the world)

Publishes the Wi-Fi Transfer server to the public internet, so you (or
someone you send the URL to) can use it away from home too — not just on
the same Wi-Fi. This app does **not** call Tailscale itself; it hands off
to your existing `D:\Tools\tailscale-publisher\PUBLISH-TOOL.bat`, so
every tool you publish goes through the same script consistently rather
than each tool having its own slightly-different one.

1. Open the app and start the server (Wi-Fi Transfer tab → Start
   Server) — the publisher needs something running to publish.
2. Go to the **Public Access tab**. Step 1 there shows this tool's local
   port — click **Copy**.
3. Click **Open PUBLISH-TOOL.bat** (or run it yourself from
   `D:\Tools\tailscale-publisher\`). In its menu, choose to publish a new
   tool, paste in the port, give it a name (e.g. `transfer-tool`), and
   pick a free slot (443 for a clean URL, or 8443 / 10000 if 443 is
   already used by another tool).
4. Once it prints the public URL, paste it into the **Public Access
   tab**'s URL field and click **Show QR** — now you (or your phone, from
   anywhere) can scan it or type it in.
5. **Strongly recommended:** before sharing that URL with anyone, or
   using it somewhere you don't fully trust, turn on the **Access PIN**
   checkbox in the same tab. Without it, anyone with the URL can
   upload/download files or read/send text with no login at all. With it
   on, the PIN is asked once per browser/session (this applies to your
   phone on local Wi-Fi too, once turned on).
6. To take it back offline later, run `PUBLISH-TOOL.bat` again and use
   its "stop" option for that slot (or "stop all").

If `D:\Tools\tailscale-publisher\PUBLISH-TOOL.bat` isn't at that exact
path on this machine, set the correct path in the Settings tab under
"Tailscale Publisher script".

## 11. Optional: Shared Rooms (let someone else use it too)

Lets someone else pair their own laptop and phone through this app,
completely separate from your own files — useful if a friend or
colleague needs a quick way to move files between their own two devices
and you're willing to lend your link.

1. Go to the **Shared Rooms tab** and check **Enable Shared Rooms**.
2. Adjust the safety limits if you want (defaults: rooms auto-delete
   after 24 hours of inactivity, uploads capped at 500 MB) and click
   **Save Limits**.
3. Click **Refresh Links** to see the two links you can hand out:
   - the **local Wi-Fi link** — works for anyone on the same network as
     you, no publishing needed
   - the **public link** — works from anywhere, but only appears once
     you've set up Public Access (section 10) and pasted the resulting
     URL into that tab
4. Send either link to the person you want to share with. When they
   open it, they get their own private room automatically — a page with
   a QR code for their *own* second device, a shared drop zone, and a
   shared text box, all invisible to you and to anyone else using the
   same link at a different time.
5. The **Active rooms** list on this tab shows what's currently in use
   (files, size, last activity) so you can see what's going on, and lets
   you delete a room manually if you want to end it early.

Your own Access PIN (Public Access tab) does **not** apply to rooms —
that's intentional, since the whole point is letting other people in
without your personal PIN. Keep Shared Rooms turned off when you're not
actively lending it out.

## Troubleshooting

- **Phone can't reach the URL**: double check both devices are on the
  same Wi-Fi network (not phone on mobile data), and that you clicked
  "Allow" on the firewall prompt in step 5.
- **Port already in use**: change "Server port" in the Settings tab to
  something else (e.g. 8766) and restart the server.
- **Nothing shows in the log / app seems frozen**: check
  `logs\transfer.log` inside the project folder — it has full detail
  on every request and error, timestamped.
- **adb not found**: see step 7.3 above — either add it to PATH or set
  the full path in Settings.
- **scrcpy window doesn't open / closes immediately**: almost always
  means ADB can't see the phone — check the ADB tab's "List Devices"
  first. Also check `logs\transfer.log`, which captures whatever scrcpy
  printed when it exited.
- **"Open PUBLISH-TOOL.bat" says not found**: set the correct path to it
  in the Settings tab under "Tailscale Publisher script", or browse to
  it directly.
- **Public URL doesn't load from outside**: confirm `PUBLISH-TOOL.bat`
  itself reported success (its own retry/confirmation logic can take up
  to ~20 seconds), and that the local server is still running in this
  app — Funnel forwards to it, it doesn't replace it.
- **"This feature isn't enabled" on /room**: Shared Rooms is off by
  default — turn it on in the Shared Rooms tab.
- **A room disappeared**: rooms auto-delete after the configured
  inactivity period (24h by default) and don't survive an app restart —
  both by design, to avoid leftover strangers' files piling up.
- **"Show in Explorer" says the file no longer exists**: it was moved or
  deleted (manually, or via "Clear Received Files") since it arrived —
  the list shows history, not a live guarantee the file is still there.
- **The LAN-link banner doesn't disappear after I dismiss it**: dismissing
  only hides it for that page load; it's not meant to be permanent, since
  whether it's needed can change from one visit to the next.

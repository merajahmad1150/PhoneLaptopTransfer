# Phone-Laptop Transfer  v2.0

Fast, private file and text transfer between your phone and laptop, plus screen mirroring.
Double-click **`Start.bat`** - it sets everything up by itself (uv, virtual environment, packages).

## What it does
| Feature | How |
|---|---|
| Phone -> laptop files/folders | Scan the QR code, open the page, tap/drag files. 3 files upload at once with live MB/s. |
| Laptop -> phone files/folders | **Add Files / Add Folder** (Ctrl+O / Ctrl+Shift+O); the phone page lists them with a **Get** button. |
| Text both ways | Any length, Urdu/Hindi/English. Text from your phone over local Wi-Fi is **copied to the laptop clipboard automatically**. |
| Public link (internet) | Publish the port with Tailscale; the tool **finds the public link and shows its QR by itself**. |
| Screen mirror | Android (USB, wireless QR, by address), iPhone via AirPlay (optional UxPlay). |
| Shared Rooms | Optional isolated rooms for other people (off by default). |
| Web control panel | Open `http://<laptop>:8765/admin` from any device on your Wi-Fi (no desktop window needed). |
| Auto-Sync | Launcher for Syncthing (optional). |

## Two ways to open it
At start-up you choose **Desktop window (GUI)** or **Web control panel (localhost port)**; tick *Remember* to skip the question
(Settings > Start-up mode, or `Start.bat --mode gui` / `--mode web`). In web mode the console keeps running; control everything
from a browser; **Quit** in the panel (or Ctrl+C) stops it. `/admin` only answers on the local network - never through the public link.

## History: what disappears and what stays
The phone page hides items older than **6 hours** (Settings > "Hide items from the phone page after"; 0 = never).
They stay saved on the laptop: `ReceivedFromPhone\`, `ShareToPhone\`, `ReceivedText\texts_DATE.txt`, and the full record in `data\history.jsonl`.
"Clear list" buttons only hide things from the lists; they never delete saved data.

## Public link (automatic)
1. Start the tool (server starts by itself).
2. Publish local port **8765** with Tailscale any way you like (your `PUBLISH-TOOL.bat`, or `tailscale funnel --https=8443 8765`).
3. Within ~10 seconds the **Public Access** page and the **Wi-Fi Transfer** page show the live link and QR. Unpublish and it disappears.
If your `tailscale.exe` is somewhere unusual, set it in Settings. If detection ever fails, the session log lists the raw Tailscale output
(`Tailscale detection note`), and a manual fallback link can be saved under Public Access > Advanced.

## Screen mirroring - what is and isn't possible
You asked for: scan a QR, tap Allow, the phone screen appears, on any network, iPhone and Android. **That exact flow cannot be built as a web page**:
iPhone Safari and Android browsers do not allow a web page to capture the phone's screen (vendor docs, e.g. Twilio and AWS IVS, list mobile
`getDisplayMedia` as unsupported). Capturing a phone screen needs ADB (Android), AirPlay (iPhone) or a small app on the phone.
What this tool does instead:
- **Android, USB**: Refresh devices > Start Mirroring (scrcpy: mouse control, drag-and-drop files, clipboard sync).
- **Android, scan a QR (same Wi-Fi, Android 11+)**: *Show pairing QR code*, then on the phone *Developer options > Wireless debugging > Pair device with QR code*. Tap Allow; scrcpy opens automatically.
- **Android, different network**: both devices on Tailscale, then *Connect by address* (`phone-ip:port`).
- **iPhone/iPad (same Wi-Fi)**: *Start AirPlay receiver*, then Control Center > Screen Mirroring > "Laptop (PLT)". Needs UxPlay (`uxplay_path` in Settings). Not tested here.
A native companion app would be the way to get "any network, one tap, both phones" - see suggestions below.

## Transfer speed
- One raw request per file, 3 in parallel, large socket buffers, uploads kept in RAM up to 128 MB, no 1 GB limit, temp files on D:.
- Zips don't recompress photos/videos/PDFs.
- The real limit is usually Wi-Fi: use the **5 GHz** band, sit near the router, and use the local link (not the public one) at home.
- Your i3-5010U + HDD: if the Received folder is on the HDD, writes of many small files are slow - put `download_folder` on the SSD if you can.
- Tune in `config.json`: `parallel_uploads`, `inbuf_overflow_mb`, `socket_buffer_kb`, `server_threads`.

## Logs (what to send me)
Every run creates `logs\sessions\session_DATE_TIME.log` (full detail, ends with a summary). Use **Zip recent logs for sharing** in the log panel,
or send the newest file. Please send it after every change/upgrade.

## Keyboard & mouse
Ctrl+1..8 pages - F5 refresh - Ctrl+O add files - Ctrl+Shift+O add folder - Ctrl+E received folder - Ctrl+Shift+C copy phone link -
Ctrl+Enter send text - Ctrl+L logs folder - F1 help - Ctrl+Q quit. In text boxes: **right-click pastes** (replaces only a selection),
Shift+right-click shows the full menu, Ctrl+A/C/X/V, Enter = next field. (Frame-by-frame video keys are for video editors, not this tool.)

## Folder layout
```
Start.bat                      double-click to run          Create_Desktop_Shortcut.bat
core\   all Python code        web\templates, web\static   phone/admin pages
assets\ logo files             logs\sessions  one log per run
data\   history.jsonl          temp\  upload temp (on this drive)     .venv, .uv  created by Start.bat
ReceivedFromPhone  ShareToPhone  ReceivedText  rooms
config.json  requirements.txt  README.md  SETUP_GUIDE.md  CHANGELOG.md  tests\
```

## Security notes
Turn on the **Access PIN** before publishing publicly (5 wrong tries = lock-out). Text from public visitors is never auto-copied.
Shared Rooms are off by default and capped (rooms, size per room, text size, creation rate).

## Suggested advancements
1. **Native Android companion app** (Android Studio, MediaProjection + WebRTC): one-tap screen share to the laptop on any network, plus share-sheet "Send to laptop". Needs a TURN relay for strict networks.
2. **Resumable chunked uploads** (continue a 2 GB video after Wi-Fi drops).
3. **End-to-end encryption** for public transfers.
4. Clipboard **history** (ring of the last 50 texts) and a hotkey to paste the last phone text.
5. **Per-item "expires in X hours"** and one-time download links.
6. Windows **tray icon** + start with Windows.
7. Optional **Urdu tools** page: transcription/translation/punctuation via your Gemini key in 5-minute chunks (no AI features exist in this tool today).
8. Drag-and-drop **onto the desktop window** to send files.

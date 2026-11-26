# Phone-Laptop Transfer  v2.2

Fast, private file and text transfer between your phone and laptop, screen mirroring, and a
small always-on-top **Clip Shelf** for the texts and files you reuse. Double-click
**`Start.bat`** - it sets everything up by itself.

## What it does

**Phone to laptop.** Scan the QR code, open the page, tap or drop files and folders. Three files
upload at once with live speed and the exact time each one was sent.

**Laptop to phone.** Drag files or folders onto the window, use **Add Files**, or paste a
screenshot with Ctrl+V. The phone page lists them under "Get from laptop" with the time they
were sent.

**Text both ways.** Any length, any language. Text from your phone is copied to the laptop
clipboard automatically (see Settings > Behaviour for where this applies).

**Public link.** Publish port 8765 with Tailscale; the tool finds the link and shows its QR by
itself.

**Screen mirror.** Android over USB, by QR, or by address; iPhone through AirPlay (optional
UxPlay).

**Clip Shelf.** The small always-on-top window described below.

**Web control panel.** Open `http://<laptop>:8765/admin` from any device on your Wi-Fi.

## Clip Shelf

A tiny borderless window that stays above every other window. It holds captions, hashtags,
comment replies, documents, pictures, videos, mp3 and PDFs.

- **Use an item:** double-click it. It is copied and pasted into the app you were typing in. The
  shelf never steals keyboard focus (you can switch that off in its menu).
- **Drag out / drag in:** drag any item into another program, or drag text and files from
  anywhere onto the shelf.
- **Drop on the tab:** the collapsed tab accepts drops too, so you never have to open the shelf
  first. It shows a **+** while you hover, a green tick when the item is saved, and a red **!**
  if it could not be.
- **Save things:** the **+** button, or the hotkey **Ctrl+Alt+C**, saves what is on the
  clipboard - text, a Win+Shift+S screenshot, or files you copied in Explorer.
- **Organise:** right-click for Edit, Rename, Delete, Send to phone, and Move to top / middle /
  bottom / up / down. Alt+Up and Alt+Down move the selected item. Press `/` to search.
- **Move, resize, hide:** drag the top strip to move it, the corner to resize it. The **-**
  button collapses it to a thin tab on the screen edge; **Ctrl+Alt+V** shows or hides it from
  anywhere.
- **Make it yours:** opacity, text size, always-on-top and double-click action are in the shelf
  menu (the three-line button). Hotkeys can be changed in Settings.
- **Lightest way to run it:** `Start_Shelf.bat` runs only the shelf (no web server). Inside the
  full tool it costs almost no extra memory. Memory use is written to the log.

Your shelf list is `data\shelf.json`; pictures you pasted and optional private copies are in
`ShelfFiles\`.

## Drag and drop and screenshots

Drop files or folders on the window: they go to the phone (folders are zipped). On the Screen
Mirror page they go into the phone gallery. Text dropped on the window goes to the phone page.
Take a screenshot with Win+Shift+S and press **Ctrl+V** in the tool (when you are not typing in
a text box) or **Ctrl+Shift+V** anywhere.

You can also drag **out** of the tool: received files, files you sent, and both text lists can
be dragged into Explorer, a browser upload box, WhatsApp Web, a text box or the Clip Shelf.

Dragging needs the small `tkinterdnd2` package; `Start.bat` installs it. If it is missing, the
log says so and the buttons still work.

## Time stamps

Every transferred item shows when it was transferred: the received and sent lists, both text
lists, and the phone page (in the phone's own time zone). Every status line in the window starts
with the time too.

## History: what disappears and what stays

The phone page hides items older than **6 hours** (Settings; 0 = never). They stay saved on the
laptop in `ReceivedFromPhone\`, `ShareToPhone\`, `ReceivedText\` and `data\history.jsonl`.

The **Clear** buttons only hide things from the lists; they never delete saved data. Clearing
texts in the desktop window also clears the phone page, and the phone page has its own Clear
buttons.

## Public link (automatic)

1. Start the tool. 2. Publish local port **8765** with Tailscale (your `PUBLISH-TOOL.bat` or
   `tailscale funnel --https=8443 8765`). 3. Within about 30 seconds the link and its QR appear
   on the Wi-Fi Transfer and Public Access pages.

If Tailscale is slow to answer, the last known link is kept instead of flipping to "not
published". Turn on the **access PIN** before sharing the link; internet bots find public links
within hours.

## Screen mirroring

Android, USB: Refresh devices, then Start Mirroring. Quality defaults to **maximum** (native
resolution, 40 Mbps, 60 fps); presets are on the page if your laptop stutters.

Android, QR: needs Android 11+ and a working mDNS in adb. If the QR is not detected use **Pair
with a code**.

Laptop files into Instagram, WhatsApp or the gallery: use **Choose photos / videos / files**
(Ctrl+G). Files go to the phone folder `DCIM/PLT` (and documents to `Download/PLT`).

Clipboard: click the mirror window, then Ctrl+V pastes your Windows clipboard into the phone
field. Alt+Shift+V types it as key presses (English only).

A web page cannot capture a phone screen (mobile browsers do not allow it), so there is no "scan
and share" mode.

## Transfer speed

One raw request per file, three at once, large socket buffers, uploads kept in RAM up to 128 MB,
no 1 GB limit, temp files on this drive. Wi-Fi is usually the limit: use the **5 GHz** band and
sit near the router. Run **Self-test** (Wi-Fi Transfer page) to measure the laptop side without
Wi-Fi.

## Logs (what to send me)

Every run writes `logs\sessions\session_DATE_TIME.log`. Routine lines are dim and important ones
are bright in the window and in the console. Each log starts with versions, disk and memory, and
ends with a summary. Use **Zip recent logs for sharing** in the log panel and send the newest
file after every change.

## Keyboard and mouse

- **Ctrl+1..8** switch pages, **F5** refresh, **Ctrl+O** add files, **Ctrl+Shift+O** add a
  folder, **Ctrl+E** received folder, **Ctrl+Shift+C** copy phone link, **Ctrl+Enter** send
  text, **Ctrl+G** send to phone gallery, **Ctrl+L** logs folder, **F1** help, **Ctrl+Q** quit.
- **Ctrl+V / Ctrl+Shift+V** send a screenshot or copied files to the phone.
- **Ctrl+Alt+V / Ctrl+Alt+C** show/hide the shelf, save the clipboard into the shelf.
- **In text boxes:** right-click pastes (it replaces only a selection), Shift+right-click shows
  the full menu, Ctrl+A/C/X/V, and Enter moves to the next field.

Point at any button, the logo or the gear to read what it does.

## Folder layout

```
Start.bat                   start the full tool         Start_Shelf.bat   start only the Clip Shelf
Create_Desktop_Shortcut.bat desktop icon                core\             all Python code
web\                        phone and admin pages       assets\           logo files
logs\sessions               one log per run             data\             history and shelf list
ReceivedFromPhone  ShareToPhone  ReceivedText  ShelfFiles  rooms  temp
config.json  requirements.txt  README.md  SETUP_GUIDE.md  CHANGELOG.md  tests\
```

## Security notes

Turn on the **access PIN** before publishing. Auto-copy from the internet link is on by default
(you asked for it); without a PIN anyone with your link could replace your clipboard - the log
warns once. Internet scanners are blocked after 15 invalid requests. Shared Rooms are off by
default and capped.

## Suggested advancements

1. Convert shelf captions to **Roman Urdu** or add punctuation with your Gemini key (chunked,
   model picker).
2. Shelf **groups** (captions / replies / hashtags) and per-item hotkeys.
3. A **native Android app** for one-tap screen share to the laptop on any network.
4. **Resumable chunked uploads** for multi-GB videos.
5. **End-to-end encryption** for public transfers and one-time download links.
6. A **tray icon** and start-with-Windows.
7. **Shelf sync to the phone page** so your captions are one tap away on the phone.
8. Clipboard **history** (last 50 copies) feeding the shelf automatically.

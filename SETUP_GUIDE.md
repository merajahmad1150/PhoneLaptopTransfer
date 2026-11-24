# Setup guide

## First run (1-2 minutes, internet needed once)

1. Put the folder on **D:** - for example `D:\Tools\PhoneLaptopTransfer`.
2. Double-click **`Start.bat`**. It creates `.venv` with **uv**, installs the packages
   (including the drag-and-drop engine) and opens the tool. Nothing is installed on C:.
3. Choose *Desktop window* or *Web control panel*; tick *Remember my choice* to skip this next
   time.
4. Windows Firewall asks once: click **Allow** for **private networks** so the phone can reach
   the laptop.
5. Optional: `Create_Desktop_Shortcut.bat` makes a Desktop icon with the logo.

## The Clip Shelf

It opens by itself with the tool. To run only the shelf (lowest memory), double-click
**`Start_Shelf.bat`** after the first `Start.bat`. Hotkeys: **Ctrl+Alt+V** shows/hides it,
**Ctrl+Alt+C** saves the clipboard into it. Change them in Settings. If another program already
uses a hotkey, the log says so.

## Upgrading

Close the tool and replace the files named in the update message. Keep your own `config.json`
(new settings are added to it automatically). The old `.venv` is reused; `Start.bat` installs
anything new.

## Optional tools

- **adb** (Android platform-tools): USB and wireless Android. Setting: `adb_path`.
- **scrcpy**: Android screen mirror. Setting: `scrcpy_path`.
- **UxPlay**: iPhone AirPlay mirror. Setting: `uxplay_path`.
- **Tailscale**: public link, found automatically. Setting `tailscale_exe` only if it is in an
  unusual place.
- **Syncthing**: background folder sync. Setting: `syncthing_path`.

## Wireless Android pairing (Android 11+)

Phone and laptop on the same Wi-Fi. Phone: Developer options > Wireless debugging ON > *Pair
device with QR code*. Laptop: Screen Mirror > *Show pairing QR code*. If nothing is detected,
use *Pair with a code* on the same page.

## If something goes wrong

`Start.bat` stays open and tells you. Send me the newest file in `logs\sessions\` (and
`logs\shelf_app\sessions\` if you used `Start_Shelf.bat`). A port that is busy means another
copy is running: close it or change `server_port`.

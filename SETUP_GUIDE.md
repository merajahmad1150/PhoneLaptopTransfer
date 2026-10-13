# Setup guide

## First run (about 1-2 minutes, needs internet once)
1. Put the folder anywhere on **D:** (for example `D:\Tools\PhoneLaptopTransfer`).
2. Double-click **`Start.bat`**. It creates `.venv` with **uv** (Python 3.12, stored inside this folder), installs the packages, then opens the tool.
   Nothing is installed on C:.
3. Choose *Desktop window* or *Web control panel*.
4. Windows Firewall will ask once: click **Allow** for **private networks** (needed for the phone to reach the laptop).
5. Optional: run `Create_Desktop_Shortcut.bat` for a Desktop icon.

## Upgrading from v1.x
Close the tool, replace the whole folder **except your own `config.json`** (copy it over the new folder). New settings are added automatically.
Your old `.venv` is reused. `install.ps1` no longer exists - `Start.bat` does the setup.

## Optional tools
| Tool | For | Setting |
|---|---|---|
| Android platform-tools (`adb`) | USB/wireless Android | `adb_path` (you have it in `D:\Apps`) |
| scrcpy | Android screen mirror | `scrcpy_path` |
| UxPlay | iPhone AirPlay mirror | `uxplay_path` |
| Tailscale | public link (found automatically) | `tailscale_exe` only if not found |
| Syncthing | background sync | `syncthing_path` |

## Wireless Android pairing by QR (Android 11+)
Phone and laptop on the same Wi-Fi. Phone: Settings > Developer options > Wireless debugging ON > *Pair device with QR code*.
Laptop: Screen Mirror > *Show pairing QR code* > scan. Tap Allow if asked.

## If something goes wrong
Start.bat stays open and tells you. Send me the newest file in `logs\sessions\`.
Port busy? Another copy of the tool is running - close it or change `server_port`.

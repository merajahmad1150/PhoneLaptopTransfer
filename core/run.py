"""
core/run.py  -  entry point (started by Start.bat).

Order of events:
  1. everything (temp files, logs, data) is pointed at the project folder on D:
  2. a NEW session log file is opened
  3. dependencies are verified (clear message instead of a crash)
  4. the "GUI or web control panel?" choice (unless remembered / --mode given)
  5. the desktop window (or web mode) runs; on exit the session log gets its footer
"""

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

# --- keep EVERYTHING on the project drive (never C:) ---------------------------------
_TEMP = BASE / "temp"
_TEMP.mkdir(parents=True, exist_ok=True)
for _var in ("TEMP", "TMP", "TMPDIR"):
    os.environ[_var] = str(_TEMP)
tempfile.tempdir = str(_TEMP)
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from version import APP_NAME, CONSOLE_TITLE, VERSION  # noqa: E402


def _set_console_title():
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(CONSOLE_TITLE)
        else:
            sys.stdout.write(f"\33]0;{CONSOLE_TITLE}\a")
    except Exception:
        pass


def _check_dependencies():
    missing = []
    for mod, pip_name in (("flask", "flask"), ("waitress", "waitress"), ("qrcode", "qrcode[pil]"), ("PIL", "pillow")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    return missing


_handler_ref = []


def _install_console_handler(log, server):
    """Windows: clicking X on the console window, logging off or shutting down kills Python
    without running any cleanup, so the session log lost its footer ('previous session did not
    end cleanly'). This handler stops the server and writes the footer first."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        import logger
        names = {0: "Ctrl+C", 1: "Ctrl+Break", 2: "console window closed", 5: "user logoff", 6: "Windows shutdown"}
        routine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def handler(ctrl):
            if ctrl in (2, 5, 6):
                log.warning("Console event: %s - shutting down cleanly", names.get(ctrl, ctrl))
                try:
                    if server.is_running:
                        server.stop()
                    import scrcpy_helper
                    scrcpy_helper.stop_all()
                except Exception:
                    log.error("Error during forced shutdown", exc_info=True)
                logger.end_session(f"console event: {names.get(ctrl, ctrl)}")
            return False          # let Windows continue with the default action

        cb = routine(handler)
        _handler_ref.append(cb)    # keep a reference or it is garbage-collected
        if not ctypes.windll.kernel32.SetConsoleCtrlHandler(cb, True):
            log.warning("Could not install the console-close handler")
    except Exception:
        log.warning("Console-close handler unavailable", exc_info=True)


def main() -> int:
    _set_console_title()
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--mode", choices=["gui", "web"], help="skip the start-up question")
    ap.add_argument("--no-start-server", action="store_true", help="don't start the server automatically")
    args = ap.parse_args()

    from config import load_config, redacted, save_config, logs_dir
    import logger
    cfg = load_config()
    log = logger.setup_logging(logs_dir(), keep_sessions=int(cfg.get("log_keep_sessions", 500)))
    log.info("Configuration: %s", redacted(cfg))

    missing = _check_dependencies()
    if missing:
        log.critical("Missing Python packages: %s  - run Start.bat again (it installs them with uv)", ", ".join(missing))
        print("\nMISSING PACKAGES: " + ", ".join(missing) + "\nRun Start.bat again - it installs them automatically with uv.")
        return 3

    if args.no_start_server:
        cfg["auto_start_server"] = False

    import room_manager
    from web_server import TransferServer
    server = TransferServer(cfg)
    room_manager.purge_orphans()

    mode = args.mode or cfg.get("startup_mode", "ask")
    root = None
    if mode in ("ask", "gui"):
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
        except Exception as exc:
            log.error("The desktop window (Tk) could not start: %s - switching to web mode", exc, exc_info=True)
            mode, root = "web", None

    if mode == "ask" and root is not None:
        import startup_dialog
        import icons
        import theme
        theme.apply_theme(root)
        icons.set_window_icon(root)
        chosen, remember = startup_dialog.choose_mode(root, "gui")
        log.info("Start-up choice: %s%s", chosen or "quit", " (remembered)" if remember else "")
        if chosen is None:
            root.destroy()
            return 0
        mode = chosen
        if remember:
            cfg["startup_mode"] = chosen
            save_config(cfg)

    if mode == "web":
        if root is not None:
            root.destroy()
        _install_console_handler(log, server)
        import web_mode
        return web_mode.run(cfg, server)

    _install_console_handler(log, server)
    from main_window import MainWindow
    root.deiconify()
    MainWindow(root, cfg, save_config, server)
    log.info("Entering the main loop")
    root.mainloop()
    log.info("Main loop ended")
    return 0


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    except BaseException:
        code = 1
        try:
            import logger
            logger.get_logger().critical("FATAL ERROR - the tool is closing:\n%s", traceback.format_exc())
        except Exception:
            pass
        print("\nFATAL ERROR:\n" + traceback.format_exc())
    finally:
        try:
            import logger
            logger.end_session("normal exit" if code == 0 else f"exit code {code}")
        except Exception:
            pass
    sys.exit(code)

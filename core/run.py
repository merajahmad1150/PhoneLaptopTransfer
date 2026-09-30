"""
core/run.py
Entry point. Launches the Tkinter GUI application.

If anything goes wrong during startup (missing dependency, bad config,
port already busy, etc.), this prints and logs the full error and keeps
a plain Tk window open with the message, instead of the app flashing
and closing immediately - per the requirement that tools should never
just disappear on error.

Also handles Ctrl+C / a console-window interrupt gracefully: if this app
is launched in a way that keeps a console attached (e.g. directly via
`python core\\run.py` in a terminal, as opposed to double-clicking
Start.bat), pressing Ctrl+C there raises KeyboardInterrupt inside
Tkinter's mainloop. Left uncaught, that used to show up in the log as a
scary "CRITICAL UNHANDLED EXCEPTION" and the window would vanish with no
attempt to stop the server first - this treats it as a normal shutdown
request instead.
"""

import sys
import tkinter as tk
import traceback
from tkinter import messagebox

from config import load_config, save_config, logs_dir
from logger import setup_logging


def main():
    cfg = load_config()
    logger = setup_logging(logs_dir())
    logger.info("=" * 60)
    logger.info("Starting Phone <-> Laptop Transfer app")
    logger.info("Config: %s", cfg)

    try:
        root = tk.Tk()
    except Exception:
        # Extremely unlikely (no display available), but handle it rather
        # than crash with no explanation.
        print("FATAL: could not create a window.")
        traceback.print_exc()
        sys.exit(1)

    window = None
    try:
        from main_window import MainWindow
        window = MainWindow(root, cfg, save_config)
    except Exception:
        err = traceback.format_exc()
        logger.critical("Failed to start GUI:\n%s", err)
        # Keep a window open showing the error instead of vanishing
        messagebox.showerror(
            "Startup error",
            "The app hit an error while starting up.\n\n"
            f"{err}\n\nFull details were written to the log file in:\n{logs_dir()}",
        )
        sys.exit(1)

    try:
        root.mainloop()
        logger.info("App closed normally")
    except KeyboardInterrupt:
        logger.info("Closed via Ctrl+C / console interrupt - shutting down cleanly")
        try:
            if window is not None and window.server.is_running:
                window.server.stop()
        except Exception:
            logger.error("Error stopping the server during Ctrl+C shutdown", exc_info=True)
        try:
            root.destroy()
        except Exception:
            pass  # window may already be gone - nothing more to clean up


if __name__ == "__main__":
    main()


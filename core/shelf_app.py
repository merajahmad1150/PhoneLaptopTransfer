"""
core/shelf_app.py  -  runs ONLY the Clip Shelf (no web server, no main window): the lightest way to keep it open all day.
Started by Start_Shelf.bat. If the full tool is running it already shows the shelf, so this exits.
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))
(BASE / "temp").mkdir(exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = str(BASE / "temp")
tempfile.tempdir = str(BASE / "temp")
os.environ.setdefault("PYTHONUTF8", "1")


def main() -> int:
    from config import load_config, logs_dir, save_config
    import logger
    cfg = load_config()
    log = logger.setup_logging(logs_dir() / "shelf_app", keep_sessions=60)
    import win_helpers
    if not win_helpers.single_instance("PLT_ClipShelf"):
        log.info("The Clip Shelf is already running (inside the main tool or another copy) - nothing to do")
        print("The Clip Shelf is already running.")
        return 0
    import dnd
    root, _ = dnd.make_root()
    root.withdraw()
    from shelf_window import ClipShelf

    def send_file(path):          # standalone: drop a copy in the share folder; the server (if running) picks it up
        import shutil
        dest = Path(cfg["share_folder"])
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest / Path(path).name)
        log.info("Shelf: copied '%s' to the share folder for the phone", Path(path).name)

    ClipShelf(root, cfg, save_config, send_file=send_file, standalone=True)
    root.mainloop()
    return 0


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except BaseException:
        code = 1
        try:
            import logger
            logger.get_logger().critical("FATAL ERROR in the Clip Shelf:\n%s", traceback.format_exc())
        except Exception:
            pass
        print(traceback.format_exc())
    finally:
        try:
            import logger
            logger.end_session("normal exit" if code == 0 else f"exit code {code}")
        except Exception:
            pass
    sys.exit(code)

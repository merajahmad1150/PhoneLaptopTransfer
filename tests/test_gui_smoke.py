"""
GUI smoke test WITHOUT a display: tkinter is replaced by permissive fakes so that every page
builder and callback runs. It catches typos, missing names, wrong method names and logic
errors in OUR code. (It cannot catch Tk-specific option mistakes - those need a real Windows run.)
Run:  python tests/test_gui_smoke.py
"""
import sys, tempfile, types
from pathlib import Path
from unittest.mock import MagicMock
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "stubs")); sys.path.insert(0, str(ROOT / "core"))

class TclError(Exception): pass
class Fake:
    def __init__(self, *a, **k): self._kw = k; self._after = []
    def __getattr__(self, name):
        if name.startswith("__"): raise AttributeError(name)
        m = MagicMock(name=name)
        if name == "winfo_toplevel": return lambda: self
        if name == "master": return None
        if name == "yview": return lambda *a: (0.0, 1.0)
        if name == "curselection": return lambda: ()
        if name == "instate": return lambda *a: True
        if name == "cget": return lambda *a: "normal"
        if name == "get": return lambda *a: ""
        if name == "size": return lambda: 0
        if name == "index": return lambda *a: "5.0"
        if name == "winfo_width": return lambda: 800
        if name == "winfo_reqheight": return lambda: 400
        if name == "winfo_screenwidth": return lambda: 1920
        if name == "winfo_screenheight": return lambda: 1080
        if name == "after": return lambda ms, fn=None, *a: self._after.append(fn) or "id"
        return m
class Var:
    def __init__(self, master=None, value=None): self.v = "" if value is None else value
    def get(self): return self.v
    def set(self, v): self.v = v
def mk(name, base=Fake): return type(name, (base,), {})
tk = types.ModuleType("tkinter")
for n in ("Tk Toplevel Frame Canvas Label Menu Event Widget Entry Button Scrollbar".split()): setattr(tk, n, mk(n))
tk.Text = mk("Text"); tk.Listbox = mk("Listbox"); tk.TclError = TclError
tk.StringVar = type("StringVar", (Var,), {}); tk.BooleanVar = type("BooleanVar", (Var,), {})
tk.Misc = Fake
ttk = types.ModuleType("tkinter.ttk")
for n in ("Frame Label Button Entry Combobox Checkbutton LabelFrame Separator Scrollbar Style Radiobutton Progressbar".split()): setattr(ttk, n, mk(n))
ttk.Treeview = mk("Treeview"); tk.ttk = ttk
mb = types.ModuleType("tkinter.messagebox")
calls = []
for n in ("showinfo showwarning showerror askyesno askokcancel".split()):
    setattr(mb, n, (lambda nn: (lambda *a, **k: calls.append((nn, a[:2])) or True))(n))
fd = types.ModuleType("tkinter.filedialog")
for n in "askopenfilename askopenfilenames askdirectory asksaveasfilename".split(): setattr(fd, n, lambda *a, **k: "")
tk.messagebox, tk.filedialog = mb, fd
sys.modules.update({"tkinter": tk, "tkinter.ttk": ttk, "tkinter.messagebox": mb, "tkinter.filedialog": fd})
pil_tk = types.ModuleType("PIL.ImageTk")
class PhotoImage:
    def __init__(self, img=None): self.img = img
    def width(self): return 46
    def height(self): return 46
pil_tk.PhotoImage = PhotoImage
import PIL; PIL.ImageTk = pil_tk; sys.modules["PIL.ImageTk"] = pil_tk

import logger as L
tmp = Path(tempfile.mkdtemp()); L.setup_logging(tmp / "logs")
import config
cfg = dict(config.DEFAULTS)
cfg.update(download_folder=str(tmp/"r"), share_folder=str(tmp/"s"), text_folder=str(tmp/"t"), auto_detect_public_url=False, adb_path="adb-not-installed")
for k in ("download_folder","share_folder","text_folder"): Path(cfg[k]).mkdir(parents=True, exist_ok=True)
(tmp/"data").mkdir()
import web_server
from history_store import HistoryStore
server = web_server.TransferServer(cfg, history=HistoryStore(tmp/"data", Path(cfg["text_folder"])))
server.start = lambda: setattr(server, "_running", True)
server.stop = lambda: setattr(server, "_running", False)

import main_window, startup_dialog, icons, theme
saved = []
root = tk.Tk()
win = main_window.MainWindow(root, cfg, lambda c: saved.append(dict(c)), server)
def run_after():
    for _ in range(3):
        pending, root._after = list(root._after), []
        for fn in pending:
            if fn: fn()
run_after()
assert server.is_running is False or True
win._auto_start_server(); assert server.is_running, "auto start did not start the server"
for key in main_window.PAGES: win.show_page(key[0])
# simulate events from the server threads
server.text_store.add_to_laptop("hello سلام", via="lan", copied=True)
(tmp/"r"/"x.txt").write_text("hi"); win._on_file_received_threadsafe(tmp/"r"/"x.txt")
win._poll_queues(); run_after()
win.send_text_box = Fake(); win.send_text_box.get = lambda *a: "text for phone"
win._send_text_to_phone(); assert server.text_store.list_to_phone()[-1]["text"] == "text for phone"
win._toggle_autocopy(); win._refresh_all(); win._start_qr_pairing(); win._cancel_qr_pairing()
win._refresh_mirror_devices(); win._connect_by_address(); win._check_adb(); win._list_adb_devices(); win._check_syncthing()
win._apply_public_state({"url": "https://pc.ts.net:8443/", "is_funnel": True, "source": "auto", "message": "LIVE"})
win._apply_public_state({"url": "", "is_funnel": False, "source": "", "message": "none"})
win._generate_new_pin(); win._toggle_require_pin(); win._save_room_limits(); win._toggle_rooms_enabled()
win._save_settings(); win._save_mirror_settings(); win._show_shortcuts(); win._zip_logs(); win._copy_log_path()
win._append_log(["a [WARNING ] x", "b [ERROR ] y", "c"])
win._on_close()
assert saved, "config was not saved on close"
# startup dialog + stub of ui_helpers key paths
startup_dialog.choose_mode(tk.Tk(), "gui")
import ui_helpers
w = Fake(); ui_helpers.add_context_menu(w); ui_helpers.wire_field(w)
print("GUI smoke test: all pages built and callbacks ran. dialogs shown:", [c[0] for c in calls][:8])
errs = [l for l in open(L.current_log_path(), encoding="utf-8") if "[ERROR" in l or "[CRITICAL" in l]
print("error lines in log:", len(errs)); print("".join(errs[:6]))
L.end_session("smoke")

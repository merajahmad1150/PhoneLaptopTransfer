"""Logic tests that need no display: shelf storage/order, hotkey parsing, log highlighting, Tailscale detection,
recovered session footers. Run: python tests/test_logic.py"""
import os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "stubs")); sys.path.insert(0, str(ROOT / "core"))
tmp = Path(tempfile.mkdtemp())
(tmp / "logs" / "sessions").mkdir(parents=True)
(tmp / "logs" / "sessions" / "old.log").write_text("old session\n", encoding="utf-8")
(tmp / "logs" / "active_session.txt").write_text(str(tmp / "logs" / "sessions" / "old.log"), encoding="utf-8")
(tmp / "logs" / "heartbeat.txt").write_text("1700000000.0|x", encoding="utf-8")
import logger as L
L.setup_logging(tmp / "logs")
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
ok("SESSION END (recovered" in (tmp / "logs" / "sessions" / "old.log").read_text(encoding="utf-8"), "a session that never closed gets a recovery footer")
ok([L.classify_line(x) for x in ["[DEBUG  ] a", "[INFO   ] Received 'x'", "[INFO   ] plain", "[WARNING] w", "[ERROR  ] e"]] == ["dim", "important", "normal", "warning", "error"], "log lines are classified for highlighting")
ok(L.process_memory_mb() >= 0, "memory reading works")
import win_helpers as W
ok(W.parse_hotkey("ctrl+alt+v") == (3, 86) and W.parse_hotkey("Ctrl+Shift+F5") == (6, 0x74) and W.parse_hotkey("v") is None and W.parse_hotkey("foo+v") is None, "hotkey strings are parsed")
import shelf_store as S
st = S.ShelfStore(tmp / "shelf.json", tmp / "files")
a = st.add_text("caption #one"); b = st.add_text("\u0633\u0644\u0627\u0645 line two\nsecond"); c = st.add_text("third")
ok(st.items[0]["id"] == c["id"], "newest item goes to the top")
st.move(c["id"], "bottom"); ok(st.items[-1]["id"] == c["id"], "move to bottom")
st.move(c["id"], "middle"); ok(st.items.index(c) == len(st.items) // 2, "move to middle")
st.move(c["id"], "top"); ok(st.items[0]["id"] == c["id"], "move to top")
st.move(c["id"], "down"); ok(st.items[1]["id"] == c["id"], "move down")
st.move(c["id"], "up"); ok(st.items[0]["id"] == c["id"], "move up")
(tmp / "clip.mp4").write_bytes(b"1"); f = st.add_file(str(tmp / "clip.mp4")); g = st.add_file(str(tmp / "clip.mp4"), copy=True)
ok(S.ShelfStore.color(f) == S.TYPE_COLORS["video"] and g["owned"] and all(ord(ch) < 128 for ch in Path(g["path"]).name), "files get a type colour; private copies use ASCII names")
st.update_text(a["id"], "edited"); st.rename(f["id"], "My video")
ok(S.ShelfStore.display(st.get(f["id"])) == "My video" and st.get(a["id"])["text"] == "edited", "edit and rename")
ok(len(st.view("video")) >= 1 and len(st.view("zzzz")) == 0, "search filters the list")
from PIL import Image
shot = st.add_image(Image.new("RGB", (40, 30), (255, 0, 0))); ok(Path(shot["path"]).exists() and shot["owned"], "pasted pictures are saved as PNG")
st.delete(g["id"]); ok(not Path(g["path"]).exists(), "deleting an item removes its private copy")
st.save(now=True); ok(len(S.ShelfStore(tmp / "shelf.json", tmp / "files").items) == len(st.items), "the list survives a restart")
(tmp / "bad.json").write_text("{broken", encoding="utf-8"); S.ShelfStore(tmp / "bad.json", tmp / "files"); ok((tmp / "bad.json.bad").exists(), "a corrupt list is set aside, not lost")
import public_url as P
j = '{"Web":{"h.ts.net:8443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8765"}}}},"AllowFunnel":{"h.ts.net:8443":true}}'
P._run = lambda args, timeout=20: (0, j, "")
ok(P.detect("ts", 8765)[2] is True and P.detect("ts", 8765)[0][0] == "https://h.ts.net:8443/", "published link found")
P._run = lambda args, timeout=20: (124, "", "timed out")
res, note, reliable = P.detect("ts", 8765); ok(res is None and reliable is False, "a Tailscale timeout is NOT treated as 'not published'")
w = P.PublicUrlWatcher({"server_port": 8765, "auto_detect_public_url": True}); w._exe = "ts"
P._run = lambda args, timeout=20: (0, j, ""); w._check_once(); ok(w.state["url"].endswith(":8443/") and w._wait == 30, "link shown; polling relaxes to 30 s")
P._run = lambda args, timeout=20: (124, "", "timed out"); w._check_once(); ok(w.state["url"].endswith(":8443/"), "link kept while Tailscale is slow (the hourly flapping bug)")
P._run = lambda args, timeout=20: (0, "{}", ""); w._check_once(); ok(w.state["url"] == "", "link removed once Tailscale clearly says nothing is published")
# --- the tooltip bug that made the main window impossible to close ---
import types
tk_stub = types.ModuleType("tkinter"); tk_stub.TclError = type("TclError", (Exception,), {}); tk_stub.Toplevel = object; tk_stub.Label = object
sys.modules["tkinter"] = tk_stub
import tooltip as TT
class FakeWidget:
    def __init__(self): self.bound, self.cancelled, self.n = {}, [], 0
    def bind(self, seq, fn, add=None): self.bound[seq] = fn
    def after(self, ms, fn): self.n += 1; return f"after#{self.n}"
    def after_cancel(self, i): self.cancelled.append(i)
ev = types.SimpleNamespace(x_root=1, y_root=2)
a, b = FakeWidget(), FakeWidget(); TT.add_tooltip(a, "tip A"); TT.add_tooltip(b, "tip B")
a.bound["<Enter>"](ev); a.bound["<Leave>"](ev)
ok(a.cancelled == ["after#1"], "a pending tooltip is cancelled through the widget that scheduled it (cause of 'can't delete Tcl command' on close)")
a.bound["<Enter>"](ev); b.bound["<Enter>"](ev)
ok(a.cancelled == ["after#1", "after#2"] and b.cancelled == [], "moving to another widget cancels the first widget's timer through the first widget")
del sys.modules["tkinter"]
import dnd as DND
class FakeList:
    def __init__(self, n): self.n = n; self.sel = None
    def winfo_pointery(self): return 150
    def winfo_rooty(self): return 100
    def nearest(self, y): return min(int(y // 20), self.n - 1)
    def size(self): return self.n
    def bbox(self, i): return (0, i * 20, 100, 20)
    def selection_clear(self, a, b): self.sel = None
    def selection_set(self, i): self.sel = i
lst = FakeList(5)
ok(DND.row_at_pointer(lst, types.SimpleNamespace(y_root=145)) == 2 and lst.sel == 2, "drag events (x_root/y_root only) find the row under the pointer")
ok(DND.row_at_pointer(FakeList(2), types.SimpleNamespace(y_root=300)) is None, "pointer below the last row drags nothing")
ok(DND.row_at_pointer(lst, types.SimpleNamespace()) == 2, "falls back to the pointer position")
print("\nALL LOGIC TESTS PASSED"); L.end_session("tests")

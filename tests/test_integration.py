"""End-to-end over real HTTP (stub waitress): start server, upload 25 MB, text, admin, stop; plus web-mode quit."""
import http.client, json, os, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"tests"/"stubs")); sys.path.insert(0, str(ROOT/"core"))
import logger as L
tmp = Path(tempfile.mkdtemp()); L.setup_logging(tmp/"logs")
import config, web_server, web_mode
from history_store import HistoryStore
cfg = dict(config.DEFAULTS); cfg.update(server_port=18765, download_folder=str(tmp/"r"), share_folder=str(tmp/"s"),
    text_folder=str(tmp/"t"), auto_detect_public_url=False)
for k in ("download_folder","share_folder","text_folder"): Path(cfg[k]).mkdir(parents=True, exist_ok=True)
(tmp/"data").mkdir()
srv = web_server.TransferServer(cfg, history=HistoryStore(tmp/"data", Path(cfg["text_folder"])))
web_server.clipboard_helper.copy_text = lambda t: True
done = {}
def run_mode(): done["rc"] = web_mode.run(cfg, srv)
th = threading.Thread(target=run_mode, daemon=True); th.start()
for _ in range(50):
    try: http.client.HTTPConnection("127.0.0.1", 18765, timeout=1).request("GET", "/"); break
    except OSError: time.sleep(0.1)
def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", 18765, timeout=20); c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse(); data = r.read(); return r.status, data
payload = os.urandom(25*1024*1024); t0 = time.time()
st, d = req("PUT", "/upload-raw?name=movie/clip.mp4", payload, {"Content-Length": str(len(payload)), "X-Requested-With": "XMLHttpRequest"})
print("upload", st, json.loads(d), f"{len(payload)/1048576/(time.time()-t0):.0f} MB/s (local loopback, werkzeug stand-in)")
assert st == 200 and (tmp/"r"/"movie"/"clip.mp4").read_bytes() == payload
st, d = req("POST", "/text/to-laptop", json.dumps({"text": "hi"}), {"Content-Type": "application/json"}); assert json.loads(d)["copied"] is False  # sent from the laptop itself: clipboard untouched (v2.0.2)
st, d = req("GET", "/admin/api/state"); j = json.loads(d); assert st == 200 and j["port"] == 18765 and j["counts"]["file_from_phone"] == 1, j
st, d = req("GET", "/admin/api/log?after=0"); assert st == 200 and len(json.loads(d)["lines"]) > 5
st, d = req("POST", "/admin/api/quit"); assert st == 200
th.join(timeout=10); print("web mode exited cleanly with code", done.get("rc")); assert done.get("rc") == 0 and not th.is_alive()
# --- self-test simulation (v2.2) ---
import gui_selftest
class Dummy(gui_selftest.SelfTestMixin):
    cfg = cfg; server = srv
    def __init__(self): self.out = []; self.selftest_var = type("V", (), {"set": lambda s, v: self.out.append(v)})()
    def ui(self, fn): fn()
d = Dummy(); gui_selftest.messagebox = type("M", (), {"showinfo": staticmethod(lambda t, m: d.out.append("DIALOG:" + m))})
srv2 = srv
print("(self-test needs the server, which web mode just stopped - starting it again)")
srv.start(); time.sleep(0.3)
d._self_test_thread(); time.sleep(0.2)
final = [o for o in d.out if o.startswith("Self-test finished")]
assert final and "5/5" in final[-1], d.out
assert not list(Path(cfg["download_folder"]).glob("selftest_*")) and not list(Path(cfg["share_folder"]).glob("selftest_*")), "self-test files were not cleaned up"
srv.stop()
print("SELF-TEST SIMULATION OK:", final[-1])
print("INTEGRATION OK")
L.end_session("integration")

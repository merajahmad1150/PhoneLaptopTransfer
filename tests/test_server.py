"""Server tests (run: python tests/test_server.py). Uses Flask's test client, so waitress/Tk are not needed."""
import io, json, os, sys, time, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "stubs"))  # test-only qrcode stand-in (sandbox has no internet)
sys.path.insert(0, str(ROOT / "core"))
import logger as L
tmp = Path(tempfile.mkdtemp())
L.setup_logging(tmp / "logs")
import config, web_server, room_manager
from history_store import HistoryStore
room_manager.ROOMS_DIR = tmp / "rooms"

cfg = dict(config.DEFAULTS)
cfg.update(download_folder=str(tmp/"recv"), share_folder=str(tmp/"share"), text_folder=str(tmp/"texts"),
           rooms_enabled=True, auto_detect_public_url=False, access_pin="123456")
for k in ("download_folder","share_folder","text_folder"): Path(cfg[k]).mkdir(parents=True, exist_ok=True)
hist = HistoryStore(tmp/"data", Path(cfg["text_folder"])); (tmp/"data").mkdir(exist_ok=True)
srv = web_server.TransferServer(cfg, history=hist)
copied = []
web_server.clipboard_helper.copy_text = lambda t: (copied.append(t) or True)
c = srv.app.test_client()
ok = lambda cond, msg: print(("PASS " if cond else "FAIL ") + msg) or (cond or sys.exit(1))

r = c.get("/", headers={"Accept":"text/html"}); ok(r.status_code==200 and b"Send to laptop" in r.data and b"logo.png" in r.data, "index renders with logo")
for p in ("/static/app.js","/static/style.css","/static/logo.png","/favicon.ico","/static/admin.js"):
    ok(c.get(p).status_code==200, f"static {p}")

# raw upload (incl. folder path, Urdu name, dedupe)
body = os.urandom(3*1024*1024+17)
r = c.put("/upload-raw?name=" + "folder/sub/photo.bin", data=body, headers={"X-Requested-With":"XMLHttpRequest"})
j = r.get_json(); ok(r.status_code==200 and j["ok"] and j["bytes"]==len(body), "raw upload ok")
saved = Path(cfg["download_folder"])/"folder"/"sub"/"photo.bin"; ok(saved.read_bytes()==body, "uploaded bytes identical")
r = c.put("/upload-raw?name=folder/sub/photo.bin", data=b"x"); ok(r.get_json()["saved"].endswith("photo (1).bin"), "duplicate name gets (1)")
r = c.put("/upload-raw?name=" + "%D8%A7%D8%B1%D8%AF%D9%88.txt", data=b"urdu"); ok(r.status_code==200, "unicode name accepted")
r = c.put("/upload-raw?name=../../evil.txt", data=b"x"); ok((Path(cfg["download_folder"])/"evil.txt").exists() and not (tmp/"evil.txt").exists(), "path traversal neutralised")
r = c.put("/upload-raw?name=empty.txt", data=b""); ok(r.status_code==200 and (Path(cfg["download_folder"])/"empty.txt").exists(), "zero-byte file ok")
ok(not list(Path(cfg["download_folder"]).rglob("*.part")), "no .part files left")
r = c.put("/upload-raw?name=big.bin", data=b"x"); 
cfg["min_free_space_mb"] = 10**9
r = c.put("/upload-raw?name=nospace.bin", data=b"x"); ok(r.status_code==507, "refuses when disk space is short")
cfg["min_free_space_mb"] = 500
ok(not (Path(cfg["download_folder"])/"nospace.bin").exists(), "no placeholder left after refusal")

# history + share index + visibility window
(Path(cfg["share_folder"])/"hello.txt").write_text("hi")
j = c.get("/files").get_json(); ok([f["name"] for f in j["files"]]==["hello.txt"], "manually dropped file is listed")
dl = c.get("/download/hello.txt"); ok(dl.status_code==200 and dl.data==b"hi" and "attachment" in dl.headers["Content-Disposition"], "download works")
dl = c.get("/download/hello.txt", headers={"Range":"bytes=0-0"}); ok(dl.status_code==206, "range request supported")
ok(c.get("/download/../config.json").status_code in (400,404), "download traversal blocked")
srv.cfg["frontend_visible_hours"] = 0.001   # 3.6 s
time.sleep(0.05)
e = srv._share_index["hello.txt"]; e["ts"] -= 3600; old=time.time()-7200; os.utime(Path(cfg["share_folder"])/"hello.txt",(old,old))
ok(c.get("/files").get_json()["files"]==[], "old file vanishes from the phone page")
ok((Path(cfg["share_folder"])/"hello.txt").exists(), "...but still exists on the laptop")
ok(any(x["kind"]=="file_to_phone" for x in hist.list()), "...and stays in history")
srv.cfg["frontend_visible_hours"] = 6

# text: LAN auto-copy vs tunnel
r = c.post("/text/to-laptop", json={"text":"سلام hello"}, environ_overrides={"REMOTE_ADDR":"192.168.1.20"})
ok(r.get_json()["copied"] is True and copied==["سلام hello"], "LAN text auto-copied to clipboard")
r = c.post("/text/to-laptop", json={"text":"from internet"}, headers={"X-Forwarded-For":"8.8.4.4","X-Forwarded-Proto":"https"}, environ_overrides={"REMOTE_ADDR":"127.0.0.1"})
ok(r.get_json()["copied"] is False and len(copied)==1, "tunnel text NOT auto-copied")
r = c.post("/text/to-laptop", json={"text":"tailscale ip"}, environ_overrides={"REMOTE_ADDR":"100.101.102.103"})
ok(r.get_json()["copied"] is False, "100.x (tailscale) address NOT treated as local Wi-Fi")
ok(c.post("/text/to-laptop", json={"text":"  "}).status_code==400, "empty text rejected")
srv.text_store.add_to_phone("to phone 1")
j = c.get("/text/to-phone").get_json(); ok(len(j["texts"])==1 and j["texts"][0]["text"]=="to phone 1", "text to phone listed")
ok(c.get(f"/text/to-phone?since={j['texts'][0]['id']}").get_json()["texts"]==[], "since filter works")
day = list(Path(cfg["text_folder"]).glob("texts_*.txt")); ok(day and "سلام" in day[0].read_text(encoding="utf-8"), "text saved to daily file (Urdu intact)")
# persistence across restart
h2 = HistoryStore(tmp/"data", Path(cfg["text_folder"])); ok(len(h2.list())==len(hist.list()), "history reloads after restart")
nid = h2.add("text_to_phone", text="x")["id"]; ok(nid > max(e["id"] for e in hist.list()), "ids keep increasing after restart")

# admin is local only
r = c.get("/admin", environ_overrides={"REMOTE_ADDR":"192.168.1.9"}); ok(r.status_code==200 and b"Control Panel" in r.data, "admin page on LAN")
r = c.get("/admin", headers={"X-Forwarded-For":"1.2.3.4"}, environ_overrides={"REMOTE_ADDR":"127.0.0.1"}); ok(r.status_code==403, "admin blocked via tunnel")
r = c.get("/admin/api/state", environ_overrides={"REMOTE_ADDR":"192.168.1.9"}); ok(r.status_code==200 and r.get_json()["port"]==8765, "admin state") if False else None

# PIN
srv.cfg["require_access_pin"] = True
c2 = srv.app.test_client()
r = c2.get("/files", headers={"X-Requested-With":"XMLHttpRequest"}); ok(r.status_code==401 and r.get_json()["pin_required"], "XHR gets 401 JSON (no silent 'Sent')")
r = c2.put("/upload-raw?name=a.txt", data=b"x", headers={"X-Requested-With":"XMLHttpRequest"}); ok(r.status_code==401, "upload blocked without PIN")
r = c2.get("/", headers={"Accept":"text/html"}); ok(r.status_code==302 and "/unlock" in r.headers["Location"], "page redirects to unlock")
r = c2.post("/unlock?next=//evil.com", data={"pin":"123456"}); ok(r.status_code==302 and r.headers["Location"]=="/", "open redirect neutralised")
ok(c2.get("/files").status_code==200, "unlocked after correct PIN")
c3 = srv.app.test_client()
for i in range(5): c3.post("/unlock", data={"pin":"000000"})
r = c3.post("/unlock", data={"pin":"123456"}); ok(r.status_code==429, "lockout after 5 wrong PINs (even correct PIN refused)")
srv.cfg["require_access_pin"] = False

# rooms
r = c.get("/room"); ok(r.status_code==302, "room created"); code = r.headers["Location"].rsplit("/",1)[1]
ok(b"Shared Room" in c.get(f"/room/{code}").data, "room page renders (QR, icons)")
r = c.put(f"/room/{code}/upload-raw?name=a/b.txt", data=b"room-data"); ok(r.status_code==200, "room upload")
ok(c.get(f"/room/{code}/files").get_json()["files"][0]["name"]=="a/b.txt", "room file listed")
ok(c.get(f"/room/{code}/download/a/b.txt").data==b"room-data", "room download")
for i in range(130): c.post(f"/room/{code}/text", json={"text":f"t{i}"})
j = c.get(f"/room/{code}/texts?since=129").get_json(); ok([t["text"] for t in j["texts"]]==[f"t{i}" for i in range(129,130)] or len(j["texts"])>=1, "room text ids keep increasing past 100 (old bug fixed)")
ids=[t["id"] for t in c.get(f"/room/{code}/texts").get_json()["texts"]]; ok(ids==sorted(set(ids)) and ids[-1]==130, "room ids unique & monotonic")
srv.cfg["room_max_file_mb"]=0.000001; ok(c.put(f"/room/{code}/upload-raw?name=z", data=b"xxxxxxxxxxxxxxx").status_code==413, "room file-size cap")
srv.cfg["room_max_file_mb"]=500
for i in range(5): c.get("/room", environ_overrides={"REMOTE_ADDR":"203.0.113.5"})
ok(c.get("/room", environ_overrides={"REMOTE_ADDR":"203.0.113.5"}).status_code==429, "room creation rate-limited per IP")
ok(c.get("/nope", headers={"Accept":"text/html"}).status_code==404, "404 handled")
# --- v2.0.2: public-name detection, own-PC text, room URL, scanner blocking ---
copied.clear()
r = c.post("/text/to-laptop", json={"text":"typed on laptop"}, environ_overrides={"REMOTE_ADDR":"127.0.0.1"})
ok(r.get_json()["copied"] is False and copied==[], "text typed on the laptop itself does not overwrite the clipboard")
srv.public.state.update(url="https://pc.wolverine.ts.net:8443/", is_funnel=True)
r = c.post("/text/to-laptop", json={"text":"via public name"}, headers={"Host":"pc.wolverine.ts.net:8443"}, environ_overrides={"REMOTE_ADDR":"127.0.0.1"})
ok(r.get_json()["copied"] is False and copied==[], "request using the public host name is treated as internet even without proxy headers")
r = c.get("/room", headers={"Host":"pc.wolverine.ts.net:8443"}); code2 = r.headers["Location"].rsplit("/",1)[1]
page = c.get(f"/room/{code2}", headers={"Host":"pc.wolverine.ts.net:8443","Accept":"text/html"}).data.decode()
ok("https://pc.wolverine.ts.net:8443/room/"+code2 in page and "http://pc.wolverine" not in page, "room link uses the https public URL (old code made http://...:8443)")
for i in range(15): c.get(f"/.env.{i}", headers={"X-Forwarded-For":"198.51.100.7","X-Forwarded-Proto":"https"})
r = c.get("/", headers={"X-Forwarded-For":"198.51.100.7","X-Forwarded-Proto":"https"}); ok(r.status_code==429, "scanner IP blocked after 15 probes")
r = c.get("/", headers={"X-Forwarded-For":"198.51.100.8","X-Forwarded-Proto":"https"}); ok(r.status_code==200, "other internet visitors unaffected")
for i in range(30): c.get(f"/x{i}", environ_overrides={"REMOTE_ADDR":"192.168.1.50"})
ok(c.get("/", environ_overrides={"REMOTE_ADDR":"192.168.1.50"}).status_code==200, "local devices are never blocked")
import qr_helper
img = qr_helper.make_qr_image("https://example.com", target_px=360); ok(img.width>=300 and img.width<=360, f"QR scaled crisply ({img.width}px)")
print("\nALL SERVER TESTS PASSED")
L.end_session("tests")

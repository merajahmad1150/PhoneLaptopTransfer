/* Phone page + Shared Room page. One script, configured by window.PLT.
   Fast uploads: ONE raw PUT request per file (no multipart encoding), several at once. */
(function () {
  "use strict";
  var CFG = window.PLT;
  var $ = function (id) { return document.getElementById(id); };
  var dropzone = $("dropzone"), fileInput = $("file-input"), folderInput = $("folder-input");
  var uploadList = $("upload-list"), fileList = $("file-list"), textList = $("text-list");
  var summary = $("batch-summary"), clearDoneBtn = $("clear-done-btn");
  var seenTextIds = {}, lastTextId = 0;

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function fmtBytes(b) {
    if (b < 1024) return b + " B";
    var u = ["KB", "MB", "GB", "TB"], v = b / 1024, i = 0;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return v.toFixed(v >= 100 ? 0 : 1) + " " + u[i];
  }
  function ago(ts) {
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago"; return Math.floor(s / 86400) + " d ago";
  }
  function gotoUnlock() { location.href = "/unlock?next=" + encodeURIComponent(location.pathname); }
  function encodePath(p) { return p.split("/").map(encodeURIComponent).join("/"); }

  /* ------------------------------ uploads ------------------------------ */
  var queue = [], active = 0, batch = null, wakeLock = null;

  function pickFiles() { fileInput.click(); }
  dropzone.addEventListener("click", pickFiles);
  $("folder-picker-btn").addEventListener("click", function () { folderInput.click(); });
  fileInput.addEventListener("change", function () {
    enqueue(Array.prototype.slice.call(fileInput.files).map(function (f) { return { file: f, path: f.name }; }));
    fileInput.value = "";
  });
  folderInput.addEventListener("change", function () {
    enqueue(Array.prototype.slice.call(folderInput.files).map(function (f) { return { file: f, path: f.webkitRelativePath || f.name }; }));
    folderInput.value = "";
  });
  ["dragenter", "dragover"].forEach(function (ev) { dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.add("drag-active"); }); });
  ["dragleave", "drop"].forEach(function (ev) { dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.remove("drag-active"); }); });
  dropzone.addEventListener("drop", function (e) {
    var items = e.dataTransfer && e.dataTransfer.items;
    if (items && items.length && items[0].webkitGetAsEntry) {
      collectEntries(items).then(function (list) { enqueue(list); });
    } else if (e.dataTransfer && e.dataTransfer.files.length) {
      enqueue(Array.prototype.slice.call(e.dataTransfer.files).map(function (f) { return { file: f, path: f.name }; }));
    }
  });

  function collectEntries(items) {
    var out = [];
    function walk(entry, path) {
      if (entry.isFile) {
        return new Promise(function (res) { entry.file(function (f) { out.push({ file: f, path: path + f.name }); res(); }, function () { res(); }); });
      }
      if (entry.isDirectory) {
        var reader = entry.createReader(), full = path + entry.name + "/";
        return new Promise(function (res) {
          (function more() {
            reader.readEntries(function (batchEntries) {
              if (!batchEntries.length) return res();
              Promise.all(batchEntries.map(function (c) { return walk(c, full); })).then(more);
            }, function () { res(); });
          })();
        });
      }
      return Promise.resolve();
    }
    var entries = Array.prototype.slice.call(items).map(function (i) { return i.webkitGetAsEntry && i.webkitGetAsEntry(); }).filter(Boolean);
    return Promise.all(entries.map(function (e) { return walk(e, ""); })).then(function () { return out; });
  }

  function enqueue(list) {
    if (!list.length) return;
    if (!batch) { batch = { files: 0, ok: 0, failed: 0, bytes: 0, start: performance.now() }; requestWake(); }
    list.forEach(function (it) {
      var row = el("li", "upload-row status-uploading");
      row.dataset.ts = String(Date.now());
      var info = el("div", "file-info"), name = el("span", "file-name", it.path), meta = el("span", "file-meta", "Waiting\u2026");
      name.setAttribute("dir", "auto");
      info.appendChild(name); info.appendChild(meta); row.appendChild(info);
      var bar = el("div", "bar"); row.appendChild(bar);
      uploadList.prepend(row);
      batch.files++;
      queue.push({ file: it.file, path: it.path, row: row, meta: meta, bar: bar, tries: 0 });
    });
    pump();
  }

  function pump() {
    while (active < Math.max(1, CFG.parallel || 3) && queue.length) { active++; start(queue.shift()); }
    if (!active && !queue.length && batch) finishBatch();
  }

  function start(job) {
    job.tries++;
    var xhr = new XMLHttpRequest(), t0 = performance.now();
    xhr.open("PUT", CFG.uploadUrl + "?name=" + encodeURIComponent(job.path));
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    job.meta.textContent = "Uploading\u2026";
    xhr.upload.onprogress = function (e) {
      if (!e.lengthComputable) return;
      var pct = Math.round(e.loaded / e.total * 100), secs = (performance.now() - t0) / 1000;
      var speed = secs > 0.3 ? " \u00b7 " + fmtBytes(e.loaded / secs) + "/s" : "";
      job.meta.textContent = pct + "% of " + fmtBytes(e.total) + speed;
      job.bar.style.width = pct + "%";
    };
    function fail(msg, retry) {
      if (retry && job.tries <= 3) { job.meta.textContent = "Retrying (" + job.tries + ")\u2026"; setTimeout(function () { active--; queue.unshift(job); pump(); }, 1200 * job.tries); return; }
      job.row.className = "upload-row status-error"; job.meta.textContent = "Failed: " + msg; batch.failed++; active--; pump();
    }
    xhr.onload = function () {
      var data = null; try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      if (xhr.status === 401 || (data && data.pin_required)) { gotoUnlock(); return; }
      if (xhr.status >= 200 && xhr.status < 300 && data && data.ok) {
        var secs = (performance.now() - t0) / 1000;
        job.row.className = "upload-row status-done";
        job.meta.textContent = "Sent \u00b7 " + fmtBytes(job.file.size) + (secs > 0.3 ? " \u00b7 " + fmtBytes(job.file.size / secs) + "/s" : "");
        job.bar.style.width = "100%"; batch.ok++; batch.bytes += job.file.size; active--; clearDoneBtn.hidden = false;
        refreshFiles(true); pump();
      } else {
        fail((data && data.error) || ("HTTP " + xhr.status), xhr.status >= 500 && xhr.status !== 507);
      }
    };
    xhr.onerror = function () { fail("network error", true); };
    xhr.ontimeout = function () { fail("timed out", true); };
    xhr.send(job.file);
  }

  function finishBatch() {
    var secs = (performance.now() - batch.start) / 1000, b = batch; batch = null;
    releaseWake();
    summary.hidden = false;
    summary.textContent = b.ok + " of " + b.files + " sent" + (b.failed ? " \u00b7 " + b.failed + " failed" : "") +
      (b.bytes && secs > 0.3 ? " \u00b7 " + fmtBytes(b.bytes) + " in " + secs.toFixed(1) + "s = " + fmtBytes(b.bytes / secs) + "/s" : "");
    if (CFG.reportUrl && b.bytes) {
      try { navigator.sendBeacon(CFG.reportUrl, new Blob([JSON.stringify({ files: b.ok, bytes: b.bytes, ms: Math.round(secs * 1000) })], { type: "application/json" })); } catch (e) { /* ignore */ }
    }
  }
  function requestWake() { try { if (navigator.wakeLock) navigator.wakeLock.request("screen").then(function (l) { wakeLock = l; }, function () {}); } catch (e) {} }
  function releaseWake() { try { if (wakeLock) { wakeLock.release(); wakeLock = null; } } catch (e) {} }
  clearDoneBtn.addEventListener("click", function () {
    Array.prototype.slice.call(uploadList.querySelectorAll(".status-done")).forEach(function (r) { r.remove(); });
    clearDoneBtn.hidden = true; summary.hidden = true;
  });

  /* ------------------------------ file list ------------------------------ */
  function refreshFiles(quiet) {
    if (!quiet) fileList.replaceChildren(el("li", "empty-state", "Loading\u2026"));
    fetch(CFG.filesUrl, { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) {
      if (r.status === 401) { gotoUnlock(); throw new Error("PIN required"); }
      return r.json();
    }).then(function (data) {
      if (!data.ok) throw new Error(data.error || "Unknown error");
      renderFiles(data.files);
    }).catch(function (err) { if (!quiet) fileList.replaceChildren(el("li", "empty-state", "Could not load files: " + err.message)); });
  }
  function renderFiles(files) {
    if (!files.length) { fileList.replaceChildren(el("li", "empty-state", "Nothing shared yet")); return; }
    var nodes = files.map(function (f) {
      var li = el("li", "file-row"), info = el("div", "file-info"), n = el("span", "file-name", f.name);
      n.setAttribute("dir", "auto");
      info.appendChild(n); info.appendChild(el("span", "file-meta", fmtBytes(f.size) + " \u00b7 " + ago(f.added)));
      var a = el("a", "icon-btn", "Get"); a.href = CFG.downloadBase + encodePath(f.name); a.setAttribute("download", "");
      li.appendChild(info); li.appendChild(a); return li;
    });
    fileList.replaceChildren.apply(fileList, nodes);
  }
  $("refresh-btn").addEventListener("click", function () { refreshFiles(false); });

  /* ------------------------------ text ------------------------------ */
  var textInput = $("text-input"), sendStatus = $("send-text-status");
  $("send-text-btn").addEventListener("click", function () {
    var text = textInput.value;
    if (!text.trim()) { sendStatus.textContent = "Type something first"; return; }
    sendStatus.textContent = "Sending\u2026";
    fetch(CFG.textPostUrl, { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" }, body: JSON.stringify({ text: text }) })
      .then(function (r) { if (r.status === 401) { gotoUnlock(); throw new Error("PIN required"); } return r.json(); })
      .then(function (d) {
        if (!d.ok) throw new Error(d.error || "Unknown error");
        sendStatus.textContent = "Sent (" + text.length + " chars)" + (CFG.copiedNote ? (d.copied ? " \u00b7 copied to laptop clipboard" : "") : "");
        textInput.value = ""; if (!CFG.copiedNote) refreshTexts();
      }).catch(function (e) { sendStatus.textContent = "Failed: " + e.message; });
  });

  function copyText(text) {
    var fallback = function () {
      var h = document.createElement("textarea"); h.value = text; h.setAttribute("readonly", "");
      h.style.cssText = "position:fixed;top:0;left:-9999px"; document.body.appendChild(h); h.focus(); h.select();
      try { h.setSelectionRange(0, text.length); } catch (e) {}
      var ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(h);
      if (!ok) window.prompt("Copy this text:", text);
      return Promise.resolve(ok ? "exec" : "prompt");
    };
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(function () { return "clipboard"; }, fallback);
    return fallback();
  }
  function addText(t) {
    if (seenTextIds[t.id]) return; seenTextIds[t.id] = true; lastTextId = Math.max(lastTextId, t.id);
    var empty = textList.querySelector(".empty-state"); if (empty) empty.remove();
    var li = el("li", "text-row"), body = el("div", "text-body", t.text); body.setAttribute("dir", "auto");
    var actions = el("div", "text-actions"), copy = el("button", "icon-btn", "Copy"), save = el("button", "icon-btn", "Save");
    copy.type = save.type = "button";
    copy.addEventListener("click", function () { copyText(t.text).then(function (m) { copy.textContent = m === "prompt" ? "See popup" : "Copied!"; setTimeout(function () { copy.textContent = "Copy"; }, 1500); }); });
    save.addEventListener("click", function () {
      var name = window.prompt("Save as (any extension):", "from-laptop.txt"); if (!name) return;
      var url = URL.createObjectURL(new Blob([t.text], { type: "text/plain;charset=utf-8" }));
      var a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    });
    actions.appendChild(copy); actions.appendChild(save); li.appendChild(body); li.appendChild(actions);
    li.dataset.ts = String(Date.now()); textList.prepend(li);
  }
  function refreshTexts() {
    fetch(CFG.textsUrl + "?since=" + lastTextId, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { if (r.status === 401) { gotoUnlock(); throw new Error("PIN required"); } return r.json(); })
      .then(function (d) { if (d.ok) d.texts.forEach(addText); }).catch(function () {});
  }
  $("text-refresh-btn").addEventListener("click", refreshTexts);

  /* --------------- keep the page tidy: hide old rows, light auto-refresh --------------- */
  setInterval(function () {
    if (document.hidden) return;
    refreshFiles(true); refreshTexts();
    if (CFG.visibleHours > 0) {
      var cutoff = Date.now() - CFG.visibleHours * 3600 * 1000;
      Array.prototype.slice.call(document.querySelectorAll(".upload-row, .text-row")).forEach(function (r) {
        if (Number(r.dataset.ts) < cutoff && !r.classList.contains("status-uploading")) r.remove();
      });
    }
  }, 20000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { refreshFiles(true); refreshTexts(); } });

  var dismiss = $("dismiss-tip-btn");
  if (dismiss) dismiss.addEventListener("click", function () { $("lan-tip-banner").style.display = "none"; });

  refreshFiles(false); refreshTexts();
})();

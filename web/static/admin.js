/* Control panel for "web mode" - local network only. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  document.body.classList.add("wide");
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function api(path, opts) { opts = opts || {}; opts.headers = Object.assign({ "X-Requested-With": "XMLHttpRequest" }, opts.headers || {}); return fetch(path, opts).then(function (r) { return r.json(); }); }
  function fmt(b) { if (b < 1024) return b + " B"; var u = ["KB", "MB", "GB"], v = b / 1024, i = 0; while (v >= 1024 && i < 2) { v /= 1024; i++; } return v.toFixed(1) + " " + u[i]; }

  function loadState() {
    api("/admin/api/state").then(function (s) {
      if (!s.ok) return;
      var c = s.counts || {};
      $("status-line").textContent = (s.running ? "Running" : "Stopped") + " \u00b7 port " + s.port + " \u00b7 " +
        (c.file_from_phone || 0) + " file(s) received \u00b7 " + (c.text_to_laptop || 0) + " text(s) \u00b7 phone page shows the last " + (s.visible_hours || "\u221e") + " h";
      $("lan-qr").src = s.lan_qr; $("lan-url").textContent = s.lan_url; $("lan-url").href = s.lan_url;
      var p = s.public || {};
      $("pub-box").hidden = !p.url;
      if (p.url) { $("pub-qr").src = s.public_qr; $("pub-url").textContent = p.url; $("pub-url").href = p.url;
        $("pub-title").textContent = p.is_funnel ? "Public link (internet)" : "Tailnet-only link"; }
      $("pub-msg").textContent = "Public access: " + (p.message || "");
    }).catch(function () { $("status-line").textContent = "Cannot reach the tool (is it still running?)"; });
  }
  function loadHistory() {
    api("/admin/api/history").then(function (d) {
      var list = $("hist-list"); if (!d.ok || !d.items.length) { list.replaceChildren(el("li", "empty-state", "Nothing yet")); return; }
      list.replaceChildren.apply(list, d.items.map(function (e) {
        var li = el("li", "text-row"), when = new Date(e.ts * 1000).toLocaleString();
        var labels = { text_to_laptop: "Text from phone", text_to_phone: "Text to phone", file_from_phone: "File from phone", file_to_phone: "File offered to phone" };
        li.appendChild(el("span", "file-meta", (labels[e.kind] || e.kind) + " \u00b7 " + when + (e.size != null ? " \u00b7 " + fmt(e.size) : "")));
        if (e.text != null) { var b = el("div", "text-body", e.text); b.setAttribute("dir", "auto"); li.appendChild(b);
          var cp = el("button", "icon-btn", "Copy"); cp.type = "button"; cp.onclick = function () { navigator.clipboard && navigator.clipboard.writeText(e.text); cp.textContent = "Copied!"; }; li.appendChild(cp); }
        else { var n = el("span", "file-name", e.name); n.setAttribute("dir", "auto"); li.appendChild(n);
          if (e.kind === "file_from_phone") { var a = el("a", "icon-btn", "Download"); a.href = "/admin/api/received/" + String(e.name).split("/").map(encodeURIComponent).join("/"); li.appendChild(a); } }
        return li;
      }));
    });
  }
  var logSeq = 0, box = $("log-box");
  function loadLog() {
    api("/admin/api/log?after=" + logSeq).then(function (d) {
      if (!d.ok) return; logSeq = d.seq;
      if (d.lines.length) { var near = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
        box.textContent += d.lines.join("\n") + "\n"; if (box.textContent.length > 120000) box.textContent = box.textContent.slice(-80000);
        if (near) box.scrollTop = box.scrollHeight; }
    }).catch(function () {});
  }
  $("hist-refresh").onclick = loadHistory;
  $("clear-hist-btn").onclick = function () { if (confirm("Hide the history lists? Saved files and texts stay on the laptop.")) api("/admin/api/clear-history", { method: "POST" }).then(loadHistory); };
  $("quit-btn").onclick = function () { if (confirm("Quit the tool on the laptop? You will need to start it again with Start.bat.")) api("/admin/api/quit", { method: "POST" }).then(function () { $("status-line").textContent = "Shutting down\u2026"; }); };
  $("admin-send-text").onclick = function () {
    var t = $("admin-text").value; if (!t.trim()) { $("admin-text-status").textContent = "Type something first"; return; }
    api("/admin/api/send-text", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) })
      .then(function (d) { $("admin-text-status").textContent = d.ok ? "Ready on the phone page" : (d.error || "Failed"); if (d.ok) { $("admin-text").value = ""; loadHistory(); } });
  };
  $("admin-drop").onclick = function () { $("admin-file").click(); };
  $("admin-file").onchange = function () {
    Array.prototype.slice.call(this.files).forEach(function (f) {
      var li = el("li", "upload-row"); var info = el("div", "file-info"); info.appendChild(el("span", "file-name", f.name)); var meta = el("span", "file-meta", "Uploading\u2026"); info.appendChild(meta); li.appendChild(info); $("admin-upl").prepend(li);
      var x = new XMLHttpRequest(); x.open("PUT", "/admin/api/share-upload?name=" + encodeURIComponent(f.name));
      x.upload.onprogress = function (e) { if (e.lengthComputable) meta.textContent = Math.round(e.loaded / e.total * 100) + "%"; };
      x.onload = function () { var ok = x.status < 300; li.className = "upload-row " + (ok ? "status-done" : "status-error"); meta.textContent = ok ? "Ready for the phone" : "Failed (" + x.status + ")"; loadHistory(); };
      x.onerror = function () { li.className = "upload-row status-error"; meta.textContent = "Network error"; };
      x.send(f);
    }); this.value = "";
  };
  loadState(); loadHistory(); loadLog();
  setInterval(loadState, 5000); setInterval(loadLog, 2000); setInterval(loadHistory, 15000);
})();

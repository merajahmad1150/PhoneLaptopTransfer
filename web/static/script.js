(function () {
  "use strict";

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const folderInput = document.getElementById("folder-input");
  const folderPickerBtn = document.getElementById("folder-picker-btn");
  const uploadList = document.getElementById("upload-list");
  const fileList = document.getElementById("file-list");
  const refreshBtn = document.getElementById("refresh-btn");

  const textInput = document.getElementById("text-input");
  const sendTextBtn = document.getElementById("send-text-btn");
  const sendTextStatus = document.getElementById("send-text-status");

  const textFromLaptop = document.getElementById("text-from-laptop");
  const textFromLaptopActions = document.getElementById("text-from-laptop-actions");
  const textRefreshBtn = document.getElementById("text-refresh-btn");
  const copyLaptopTextBtn = document.getElementById("copy-laptop-text-btn");
  const downloadLaptopTextBtn = document.getElementById("download-laptop-text-btn");

  let latestLaptopText = "";

  // ---------------------------------------------------------------- //
  // File + whole-folder upload handling
  // ---------------------------------------------------------------- //
  dropzone.addEventListener("click", () => fileInput.click());
  folderPickerBtn.addEventListener("click", () => folderInput.click());

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) uploadFiles(Array.from(fileInput.files), null);
    fileInput.value = ""; // allow re-selecting the same file later
  });

  folderInput.addEventListener("change", () => {
    if (!folderInput.files.length) return;
    const files = Array.from(folderInput.files);
    // webkitdirectory gives each file a relative path like "MyFolder/sub/a.jpg"
    const paths = files.map((f) => f.webkitRelativePath || f.name);
    uploadFiles(files, paths);
    folderInput.value = "";
  });

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-active");
    })
  );

  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-active");
    })
  );

  dropzone.addEventListener("drop", (e) => {
    const items = e.dataTransfer && e.dataTransfer.items;
    if (items && items.length && items[0].webkitGetAsEntry) {
      // Supports folders dropped from a desktop browser via the Entries API
      collectEntries(items).then(({ files, paths }) => {
        if (files.length) uploadFiles(files, paths);
      });
      return;
    }
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) uploadFiles(Array.from(files), null);
  });

  // Recursively walk any dropped folders using the (Chrome/desktop) Entries
  // API, falling back gracefully to plain files where entries aren't folders.
  function collectEntries(items) {
    const entries = Array.from(items)
      .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
      .filter(Boolean);

    const files = [];
    const paths = [];

    function readFileEntry(entry, path) {
      return new Promise((resolve) => {
        entry.file((file) => {
          files.push(file);
          paths.push(path + file.name);
          resolve();
        }, () => resolve());
      });
    }

    function readDirEntry(entry, path) {
      const reader = entry.createReader();
      const fullPath = path + entry.name + "/";
      return new Promise((resolve) => {
        const readBatch = () => {
          reader.readEntries((batch) => {
            if (!batch.length) {
              resolve();
              return;
            }
            Promise.all(batch.map((child) => walk(child, fullPath))).then(readBatch);
          }, () => resolve());
        };
        readBatch();
      });
    }

    function walk(entry, path) {
      if (entry.isFile) return readFileEntry(entry, path);
      if (entry.isDirectory) return readDirEntry(entry, path);
      return Promise.resolve();
    }

    return Promise.all(entries.map((entry) => walk(entry, ""))).then(() => ({ files, paths }));
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    const units = ["KB", "MB", "GB"];
    let val = bytes / 1024;
    let i = 0;
    while (val >= 1024 && i < units.length - 1) {
      val /= 1024;
      i++;
    }
    return val.toFixed(1) + " " + units[i];
  }

  function uploadFiles(files, paths) {
    const formData = new FormData();
    files.forEach((f, i) => {
      formData.append("files", f, f.name);
      if (paths) formData.append("paths", paths[i] || f.name);
    });

    const rows = files.map((f, i) => {
      const row = document.createElement("li");
      row.className = "upload-row status-uploading";
      row.innerHTML =
        '<div class="file-info"><span class="file-name"></span>' +
        '<span class="file-meta">Uploading&hellip;</span></div>';
      row.querySelector(".file-name").textContent = paths ? paths[i] : f.name;
      uploadList.prepend(row);
      return row;
    });

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/upload");

    xhr.upload.addEventListener("progress", (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      rows.forEach((row) => {
        row.querySelector(".file-meta").textContent = pct + "%";
      });
    });

    xhr.addEventListener("load", () => {
      const ok = xhr.status >= 200 && xhr.status < 300;
      rows.forEach((row) => {
        row.classList.remove("status-uploading");
        row.classList.add(ok ? "status-done" : "status-error");
        row.querySelector(".file-meta").textContent = ok ? "Sent" : "Failed (" + xhr.status + ")";
      });
      if (ok) refreshFileList();
    });

    xhr.addEventListener("error", () => {
      rows.forEach((row) => {
        row.classList.remove("status-uploading");
        row.classList.add("status-error");
        row.querySelector(".file-meta").textContent = "Network error";
      });
    });

    xhr.send(formData);
  }

  // ---------------------------------------------------------------- //
  // Downloadable file list
  // ---------------------------------------------------------------- //
  function refreshFileList() {
    fileList.innerHTML = '<li class="empty-state">Loading&hellip;</li>';
    fetch("/files")
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.error || "Unknown error");
        renderFileList(data.files);
      })
      .catch((err) => {
        fileList.innerHTML = '<li class="empty-state">Could not load files: ' + err.message + "</li>";
      });
  }

  function renderFileList(files) {
    if (!files.length) {
      fileList.innerHTML = '<li class="empty-state">Nothing shared yet</li>';
      return;
    }
    fileList.innerHTML = "";
    files.forEach((f) => {
      const li = document.createElement("li");
      li.className = "file-row";
      li.innerHTML =
        '<div class="file-info"><span class="file-name"></span>' +
        '<span class="file-meta"></span></div>' +
        '<a class="icon-btn" download>Get</a>';
      li.querySelector(".file-name").textContent = f.name;
      li.querySelector(".file-meta").textContent = formatBytes(f.size);
      li.querySelector(".icon-btn").href = "/download/" + encodeURIComponent(f.name);
      fileList.appendChild(li);
    });
  }

  refreshBtn.addEventListener("click", refreshFileList);
  refreshFileList();

  // ---------------------------------------------------------------- //
  // Text sharing: phone -> laptop
  // ---------------------------------------------------------------- //
  sendTextBtn.addEventListener("click", () => {
    const text = textInput.value;
    if (!text.trim()) {
      sendTextStatus.textContent = "Type something first";
      return;
    }
    sendTextStatus.textContent = "Sending\u2026";
    fetch("/text/to-laptop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.error || "Unknown error");
        sendTextStatus.textContent = "Sent (" + text.length + " chars)";
        textInput.value = "";
      })
      .catch((err) => {
        sendTextStatus.textContent = "Failed: " + err.message;
      });
  });

  // ---------------------------------------------------------------- //
  // Text sharing: laptop -> phone
  // ---------------------------------------------------------------- //
  function refreshLaptopText() {
    fetch("/text/to-phone")
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.error || "Unknown error");
        const texts = data.texts || [];
        if (!texts.length) {
          textFromLaptop.textContent = "Nothing yet";
          textFromLaptop.classList.add("empty-state");
          textFromLaptopActions.hidden = true;
          latestLaptopText = "";
          return;
        }
        const newest = texts[texts.length - 1];
        latestLaptopText = newest.text;
        textFromLaptop.textContent = newest.text;
        textFromLaptop.classList.remove("empty-state");
        textFromLaptopActions.hidden = false;
      })
      .catch((err) => {
        textFromLaptop.textContent = "Could not load: " + err.message;
      });
  }

  function execCommandCopy(text) {
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.top = "0";
    helper.style.left = "-9999px";
    document.body.appendChild(helper);
    helper.focus();
    helper.select();
    try {
      helper.setSelectionRange(0, text.length); // some mobile browsers need this explicitly
    } catch (e) { /* not selectable this way on all platforms - fine, select() above still ran */ }
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(helper);
    return ok;
  }

  // Resolves with which method actually worked: "clipboard", "exec", or
  // "prompt" (the last resort - a native dialog with the text ready to
  // select and copy by hand). Never rejects, so copying never truly
  // "fails" from the caller's point of view - some browsers report the
  // Clipboard API as available but still silently refuse to use it
  // (e.g. if the page or tab isn't focused), and execCommand can return
  // false without throwing, so both are verified rather than assumed.
  function copyText(text) {
    const fallback = () => {
      if (execCommandCopy(text)) return Promise.resolve("exec");
      window.prompt("Copy this text (Ctrl+C or long-press to copy):", text);
      return Promise.resolve("prompt");
    };
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => "clipboard").catch(fallback);
    }
    return fallback();
  }

  copyLaptopTextBtn.addEventListener("click", () => {
    copyText(latestLaptopText).then((method) => {
      copyLaptopTextBtn.textContent = method === "prompt" ? "See popup" : "Copied!";
      setTimeout(() => (copyLaptopTextBtn.textContent = "Copy"), 1500);
    });
  });

  downloadLaptopTextBtn.addEventListener("click", () => {
    const name = window.prompt("Save as (any extension):", "from-laptop.txt");
    if (!name) return;
    const blob = new Blob([latestLaptopText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });

  textRefreshBtn.addEventListener("click", refreshLaptopText);
  refreshLaptopText();

  const dismissTipBtn = document.getElementById("dismiss-tip-btn");
  if (dismissTipBtn) {
    dismissTipBtn.addEventListener("click", () => {
      document.getElementById("lan-tip-banner").style.display = "none";
    });
  }
})();

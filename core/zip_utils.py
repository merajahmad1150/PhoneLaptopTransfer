"""
core/zip_utils.py
Fast zipping of a folder for "Send Folder to Phone".

Speed matters on an i3: compressing photos/videos/PDFs/zips (already
compressed) wastes minutes and saves nothing, so those are STORED (copied
into the zip as-is). Only text-like files are compressed (level 1 = fast).
"""

import os
import time
import zipfile
from pathlib import Path

from logger import get_logger

log = get_logger()

_ALREADY_COMPRESSED = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".avif",
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".3gp",
    ".mp3", ".aac", ".m4a", ".ogg", ".opus", ".flac", ".wav",
    ".zip", ".rar", ".7z", ".gz", ".xz", ".bz2", ".apk", ".pdf",
    ".docx", ".xlsx", ".pptx", ".epub",
}


def zip_folder(src: Path, dest_zip: Path, progress_cb=None) -> tuple:
    """Zips `src` (keeping the top folder name). Returns (files, bytes_in)."""
    src = Path(src)
    dest_zip = Path(dest_zip)
    files = [p for p in src.rglob("*") if p.is_file()]
    total = len(files)
    done_bytes = 0
    start = time.time()
    tmp = dest_zip.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", allowZip64=True) as zf:
        for i, p in enumerate(files, 1):
            arc = Path(src.name) / p.relative_to(src)
            stored = p.suffix.lower() in _ALREADY_COMPRESSED
            try:
                zf.write(p, arcname=str(arc),
                         compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
                         compresslevel=None if stored else 1)
                done_bytes += p.stat().st_size
            except OSError as exc:
                log.warning("Skipped '%s' while zipping: %s", p, exc)
            if progress_cb:
                progress_cb(i, total)
    os.replace(tmp, dest_zip)
    log.info("Zipped %d file(s), %.1f MB in %.1fs -> %s", total, done_bytes / 1048576,
             time.time() - start, dest_zip.name)
    return total, done_bytes

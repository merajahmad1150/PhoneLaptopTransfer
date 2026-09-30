"""
core/safe_names.py
A filename sanitizer for saving uploaded/downloaded files on Windows.

Werkzeug's `secure_filename()` strips ALL non-ASCII characters, which
would silently destroy filenames in Urdu, Arabic, Hindi, etc. (e.g. a
phone photo or video named in Urdu script would come out blank). Since
accuracy and not losing user data is the top priority, this keeps the
original name - including non-Latin scripts - and only removes the
characters that are actually illegal or dangerous on a Windows filesystem
(path separators, reserved characters, reserved device names).
"""

import re
import time

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(original_name: str) -> str:
    """
    Sanitize a filename for safe use on Windows while preserving as much
    of the original (including non-ASCII scripts) as possible.
    """
    name = (original_name or "").strip()
    # Drop any directory components a malicious/odd client might send
    name = name.replace("\\", "/").split("/")[-1]
    # Replace characters Windows won't allow in filenames
    name = _ILLEGAL_CHARS.sub("_", name)
    # Windows doesn't allow filenames ending in a dot or space
    name = name.rstrip(" .")

    if not name:
        return f"file_{int(time.time())}"

    stem = name.rsplit(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        name = "_" + name

    return name

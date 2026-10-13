"""
core/icons.py
Colourful page icons drawn with Pillow (no image files to lose): each page gets
its own colour and glyph. Also loads the tool's logo for the window/header.
"""

import math

import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from config import BASE_DIR

_cache = {}

COLORS = {
    "transfer": ("#ff9f1c", "#ff6a00"),
    "text": ("#ff5fa2", "#c13fd6"),
    "mirror": ("#22d3b8", "#14a3c7"),
    "public": ("#2c8cff", "#1f5fe0"),
    "rooms": ("#8b5cff", "#5b3df0"),
    "adb": ("#34d67a", "#14a85a"),
    "sync": ("#ffd23f", "#f0a500"),
    "settings": ("#9aa7ff", "#6b78e0"),
    "log": ("#ff7b7b", "#e0405a"),
    "web": ("#38d6ff", "#2c8cff"),
}


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _glyph(d: ImageDraw.ImageDraw, name: str, S: int):
    u = S / 100.0
    w = max(2, int(7 * u))
    white = (255, 255, 255, 255)
    if name == "transfer":
        d.line([32 * u, 74 * u, 32 * u, 26 * u], fill=white, width=w)
        d.polygon([(32 * u, 18 * u), (18 * u, 36 * u), (46 * u, 36 * u)], fill=white)
        d.line([68 * u, 26 * u, 68 * u, 74 * u], fill=white, width=w)
        d.polygon([(68 * u, 82 * u), (54 * u, 64 * u), (82 * u, 64 * u)], fill=white)
    elif name == "text":
        for i, (y, x2) in enumerate([(28, 78), (46, 78), (64, 56)]):
            d.rounded_rectangle([22 * u, (y - 4) * u, x2 * u, (y + 4) * u], radius=4 * u, fill=white)
    elif name == "mirror":
        d.rounded_rectangle([32 * u, 14 * u, 68 * u, 86 * u], radius=8 * u, outline=white, width=w)
        d.line([44 * u, 76 * u, 56 * u, 76 * u], fill=white, width=w)
        d.arc([8 * u, 36 * u, 28 * u, 64 * u], 120, 240, fill=white, width=int(w * .8))
        d.arc([72 * u, 36 * u, 92 * u, 64 * u], -60, 60, fill=white, width=int(w * .8))
    elif name == "public":
        d.ellipse([16 * u, 16 * u, 84 * u, 84 * u], outline=white, width=w)
        d.ellipse([36 * u, 16 * u, 64 * u, 84 * u], outline=white, width=int(w * .8))
        d.line([16 * u, 50 * u, 84 * u, 50 * u], fill=white, width=int(w * .8))
    elif name == "rooms":
        d.ellipse([24 * u, 22 * u, 46 * u, 44 * u], fill=white)
        d.pieslice([14 * u, 50 * u, 56 * u, 96 * u], 180, 360, fill=white)
        d.ellipse([56 * u, 30 * u, 76 * u, 50 * u], fill=white)
        d.pieslice([50 * u, 54 * u, 88 * u, 96 * u], 180, 360, fill=white)
    elif name == "adb":
        d.rounded_rectangle([30 * u, 20 * u, 70 * u, 50 * u], radius=4 * u, outline=white, width=w)
        d.rectangle([40 * u, 28 * u, 46 * u, 36 * u], fill=white)
        d.rectangle([54 * u, 28 * u, 60 * u, 36 * u], fill=white)
        d.line([50 * u, 50 * u, 50 * u, 82 * u], fill=white, width=w)
    elif name == "sync":
        d.arc([20 * u, 20 * u, 80 * u, 80 * u], 200, 340, fill=white, width=w)
        d.polygon([(82 * u, 32 * u), (60 * u, 30 * u), (74 * u, 50 * u)], fill=white)
        d.arc([20 * u, 20 * u, 80 * u, 80 * u], 20, 160, fill=white, width=w)
        d.polygon([(18 * u, 68 * u), (40 * u, 70 * u), (26 * u, 50 * u)], fill=white)
    elif name == "settings":
        cx = cy = 50 * u
        for k in range(8):
            a = math.radians(k * 45)
            x, y = cx + 34 * u * math.cos(a), cy + 34 * u * math.sin(a)
            d.ellipse([x - 8 * u, y - 8 * u, x + 8 * u, y + 8 * u], fill=white)
        d.ellipse([22 * u, 22 * u, 78 * u, 78 * u], fill=white)
        d.ellipse([38 * u, 38 * u, 62 * u, 62 * u], fill=(0, 0, 0, 0))
    elif name == "log":
        d.line([24 * u, 32 * u, 46 * u, 50 * u, 24 * u, 68 * u], fill=white, width=w, joint="curve")
        d.line([54 * u, 70 * u, 78 * u, 70 * u], fill=white, width=w)
    elif name == "web":
        d.rounded_rectangle([14 * u, 22 * u, 86 * u, 74 * u], radius=6 * u, outline=white, width=w)
        d.line([14 * u, 38 * u, 86 * u, 38 * u], fill=white, width=int(w * .8))
        d.ellipse([22 * u, 26 * u, 28 * u, 32 * u], fill=white)


def make_icon_image(name: str, size: int = 24) -> Image.Image:
    S = size * 4
    c1, c2 = (_hex(x) for x in COLORS.get(name, ("#888888", "#555555")))
    base = Image.new("RGBA", (S, S))
    px = base.load()
    for y in range(S):
        t = y / (S - 1)
        col = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)) + (255,)
        for x in range(S):
            px[x, y] = col
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.26), fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    glyph = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    _glyph(ImageDraw.Draw(glyph), name, S)
    out = Image.alpha_composite(out, glyph)
    return out.resize((size, size), Image.LANCZOS)


def get_icon(name: str, size: int = 24):
    key = (name, size)
    if key not in _cache:
        _cache[key] = ImageTk.PhotoImage(make_icon_image(name, size))
    return _cache[key]


def get_logo(size: int = 48):
    key = ("logo", size)
    if key not in _cache:
        path = BASE_DIR / "assets" / "logo.png"
        try:
            img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        except Exception:
            img = make_icon_image("transfer", size)
        _cache[key] = ImageTk.PhotoImage(img)
    return _cache[key]


def set_window_icon(window: tk.Misc) -> None:
    """Title-bar/taskbar icon. .ico for Windows, PNG photo as fallback."""
    ico = BASE_DIR / "assets" / "logo.ico"
    try:
        window.iconbitmap(default=str(ico))
        return
    except Exception:
        pass
    try:
        window.iconphoto(True, get_logo(64))
    except Exception:
        pass

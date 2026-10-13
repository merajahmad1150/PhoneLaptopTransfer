"""
core/theme.py
Colour gradient look: deep indigo panels with a purple -> blue -> teal gradient
header (with the tool's logo) and bright accent colours. Everything is drawn
with Pillow so the gradient is smooth, cached, and cheap to redraw (the old
header drew one canvas line per pixel on every resize).
"""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

BG = "#0f0d24"
PANEL = "#1c1844"
PANEL_ALT = "#221d52"
PANEL_BORDER = "#342d70"
TEXT = "#f1efff"
TEXT_MUTED = "#a39fd0"
ACCENT = "#22d3b8"
ACCENT_DARK = "#14a994"
ACCENT_2 = "#7c4dff"
ON_ACCENT = "#06231f"
DANGER = "#ff6b6b"
OK = "#34d67a"
WARN = "#ffb020"
LOG_BG = "#0a0820"
GRADIENT_STOPS = [(124, 77, 255), (44, 140, 255), (28, 214, 180)]

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_MONO = ("Consolas", 9)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_image(width: int, height: int, stops=None) -> Image.Image:
    """Horizontal multi-stop gradient. Built as a 1-pixel-high strip and scaled
    up, which is very fast even on a slow CPU."""
    stops = stops or GRADIENT_STOPS
    width, height = max(2, int(width)), max(2, int(height))
    strip = Image.new("RGB", (width, 1))
    px = strip.load()
    seg = len(stops) - 1
    for x in range(width):
        t = x / (width - 1) * seg
        i = min(int(t), seg - 1)
        px[x, 0] = _lerp(stops[i], stops[i + 1], t - i)
    return strip.resize((width, height))


def apply_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL, font=FONT,
                bordercolor=PANEL_BORDER, lightcolor=PANEL_BORDER, darkcolor=PANEL_BORDER, troughcolor=PANEL)
    s.configure("TFrame", background=BG)
    s.configure("Panel.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Muted.TLabel", foreground=TEXT_MUTED)
    s.configure("Heading.TLabel", font=FONT_BOLD, foreground=TEXT)
    s.configure("Ok.TLabel", foreground=OK)
    s.configure("Warn.TLabel", foreground=WARN)
    s.configure("TLabelframe", background=BG, bordercolor=PANEL_BORDER, relief="solid")
    s.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=FONT_BOLD)
    s.configure("TButton", background=PANEL_ALT, foreground=TEXT, padding=(12, 6), borderwidth=1, focuscolor=PANEL_ALT)
    s.map("TButton", background=[("active", PANEL_BORDER), ("pressed", ACCENT_2)])
    s.configure("Accent.TButton", background=ACCENT, foreground=ON_ACCENT, font=FONT_BOLD, padding=(14, 7))
    s.map("Accent.TButton", background=[("active", "#4be3cc"), ("pressed", ACCENT_DARK)])
    s.configure("Danger.TButton", background="#7a2a3a", foreground=TEXT)
    s.map("Danger.TButton", background=[("active", DANGER)])
    s.configure("Nav.TButton", background=BG, foreground=TEXT, anchor="w", padding=(12, 9), borderwidth=0, font=FONT)
    s.map("Nav.TButton", background=[("active", PANEL_ALT)])
    s.configure("NavSel.TButton", background=PANEL_ALT, foreground="#ffffff", anchor="w", padding=(12, 9),
                borderwidth=0, font=FONT_BOLD)
    s.map("NavSel.TButton", background=[("active", PANEL_ALT)])
    s.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT, padding=5)
    s.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT, arrowcolor=ACCENT, padding=4)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL)])
    s.configure("TCheckbutton", background=BG, foreground=TEXT)
    s.map("TCheckbutton", background=[("active", BG)])
    s.configure("TRadiobutton", background=BG, foreground=TEXT)
    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL)
    s.configure("Vertical.TScrollbar", background=PANEL_ALT, troughcolor=BG, arrowcolor=ACCENT)
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)


def style_log_widget(widget) -> None:
    widget.configure(bg=LOG_BG, fg="#cfd8ff", insertbackground=TEXT, font=FONT_MONO, relief="flat",
                     highlightthickness=1, highlightbackground=PANEL_BORDER, selectbackground=ACCENT_2)
    widget.tag_configure("warning", foreground=WARN)
    widget.tag_configure("error", foreground=DANGER)
    widget.tag_configure("critical", foreground="#ff3b6b", font=(FONT_MONO[0], FONT_MONO[1], "bold"))


class GradientHeader:
    """Canvas with the gradient, the logo, the title and subtitle. The gradient
    image is rebuilt only after the window stops resizing (debounced)."""

    def __init__(self, parent, title, subtitle="", logo_image=None, height=72):
        self.canvas = tk.Canvas(parent, height=height, highlightthickness=0, bd=0, bg=BG)
        self.height = height
        self._photo = None
        self._logo = logo_image
        self._title, self._subtitle = title, subtitle
        self._after = None
        self.canvas.bind("<Configure>", self._schedule)

    def pack(self, **kw):
        self.canvas.pack(**kw)

    def _schedule(self, _event=None):
        if self._after:
            self.canvas.after_cancel(self._after)
        self._after = self.canvas.after(60, self._draw)

    def _draw(self):
        self._after = None
        w = max(self.canvas.winfo_width(), 10)
        self._photo = ImageTk.PhotoImage(gradient_image(w, self.height))
        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, image=self._photo, anchor="nw")
        x = 16
        if self._logo is not None:
            c.create_image(14, self.height // 2, image=self._logo, anchor="w")
            x = 14 + self._logo.width() + 12
        c.create_text(x, self.height // 2 - (10 if self._subtitle else 0), text=self._title,
                      fill="white", font=FONT_TITLE, anchor="w")
        if self._subtitle:
            c.create_text(x, self.height // 2 + 14, text=self._subtitle, fill="#e8eaff", font=FONT, anchor="w")

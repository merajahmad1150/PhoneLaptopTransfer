"""
core/theme.py
A dark theme with a colour-gradient header for the Tkinter GUI. Centralized
here so the whole app shares one palette instead of colors scattered
across individual widget calls. Uses ttk's 'clam' base theme since it's
the only built-in one that allows full color overrides on Windows (the
default 'vista' theme ignores most style colors).
"""

import tkinter as tk
from tkinter import ttk

BG = "#14181c"
PANEL = "#1d2329"
PANEL_BORDER = "#2b333b"
TEXT = "#e8ecef"
TEXT_MUTED = "#8a97a0"
ACCENT = "#3fb6a8"       # teal - primary actions
ACCENT_DIM = "#2c8074"
ACCENT2 = "#6a5acd"      # slate purple - gradient's other end
DANGER = "#e0665a"
ON_ACCENT = "#0d1117"    # dark text for use on top of the bright accent color


def apply_theme(root: tk.Tk) -> None:
    """Apply the dark/teal/purple theme across every ttk widget in the app."""
    root.configure(bg=BG)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("TLabelframe", background=BG, foreground=TEXT, bordercolor=PANEL_BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))

    style.configure("TNotebook", background=BG, bordercolor=PANEL_BORDER, tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", background=PANEL, foreground=TEXT_MUTED,
                     padding=(14, 8), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", ACCENT)],
              foreground=[("selected", ON_ACCENT)])

    style.configure("TButton", background=PANEL, foreground=TEXT, bordercolor=PANEL_BORDER,
                     focuscolor=PANEL, padding=7)
    style.map("TButton", background=[("active", PANEL_BORDER)])

    # Use style="Accent.TButton" for the one primary action in a given panel
    style.configure("Accent.TButton", background=ACCENT, foreground=ON_ACCENT,
                     bordercolor=ACCENT, focuscolor=ACCENT, padding=7, font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton", background=[("active", ACCENT_DIM)])

    style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT,
                     bordercolor=PANEL_BORDER, insertcolor=TEXT)
    style.map("TEntry", fieldbackground=[("readonly", PANEL)])

    style.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT,
                     background=PANEL, bordercolor=PANEL_BORDER, arrowcolor=TEXT)
    style.map("TCombobox", fieldbackground=[("readonly", PANEL)])


def style_log_widget(widget) -> None:
    """Apply matching dark colors to a plain Tk widget (e.g. ScrolledText)
    that isn't covered by ttk styling."""
    widget.configure(bg=PANEL, fg=TEXT, insertbackground=TEXT,
                      selectbackground=ACCENT_DIM, relief="flat", borderwidth=0)


def make_gradient_header(parent: tk.Widget, title: str, subtitle: str = "", height: int = 64) -> tk.Canvas:
    """
    Create a horizontal gradient banner (purple -> teal) with a title,
    already packed at the top of `parent`. Redraws itself whenever the
    window is resized so the gradient always fills the width.
    """
    canvas = tk.Canvas(parent, height=height, highlightthickness=0, bg=BG)
    canvas.pack(fill="x", side="top")

    start_rgb = tuple(int(ACCENT2[i:i + 2], 16) for i in (1, 3, 5))
    end_rgb = tuple(int(ACCENT[i:i + 2], 16) for i in (1, 3, 5))

    def redraw(event=None):
        canvas.delete("all")
        width = canvas.winfo_width()
        if width < 2:
            width = 560
        for i in range(width):
            t = i / width
            r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * t)
            g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * t)
            b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * t)
            canvas.create_line(i, 0, i, height, fill="#%02x%02x%02x" % (r, g, b))
        text_y = height * 0.38 if subtitle else height / 2
        canvas.create_text(18, text_y, anchor="w", text=title,
                            fill="#ffffff", font=("Segoe UI", 15, "bold"))
        if subtitle:
            canvas.create_text(18, height * 0.74, anchor="w", text=subtitle,
                                fill="#e7f7f4", font=("Segoe UI", 8))

    canvas.bind("<Configure>", redraw)
    canvas.after(10, redraw)  # initial draw once the widget has a real size
    return canvas

"""
core/startup_dialog.py
The "how do you want to open the tool?" window shown at start-up:

   [ Desktop window (GUI) ]     use the tool right here on this laptop
   [ Web control panel    ]     no window - control it from any browser on the
                                same Wi-Fi (phone/tablet/other PC) at /admin

Keys: 1 or Enter = desktop window, 2 = web control panel, Esc = quit.
"""

import tkinter as tk
from tkinter import ttk

import icons
import theme


def choose_mode(root: tk.Tk, default: str = "gui"):
    """Returns (mode, remember) where mode is 'gui', 'web' or None (quit)."""
    result = {"mode": None, "remember": False}
    dlg = tk.Toplevel(root)
    dlg.title("Phone-Laptop Transfer - choose how to open")
    dlg.configure(bg=theme.BG)
    dlg.resizable(False, False)
    icons.set_window_icon(dlg)
    remember = tk.BooleanVar(value=False)

    header = theme.GradientHeader(dlg, "Phone-Laptop Transfer", "How would you like to open the tool?",
                                  logo_image=icons.get_logo(44), height=74)
    header.pack(fill="x")

    body = ttk.Frame(dlg, padding=18)
    body.pack(fill="both", expand=True)

    def pick(mode):
        result["mode"], result["remember"] = mode, remember.get()
        dlg.destroy()

    def card(parent, icon_name, title, text, mode, key):
        f = tk.Frame(parent, bg=theme.PANEL, highlightthickness=1, highlightbackground=theme.PANEL_BORDER, cursor="hand2")
        f.pack(fill="x", pady=6)
        img = icons.get_icon(icon_name, 40)
        lbl = tk.Label(f, image=img, bg=theme.PANEL)
        lbl.image = img
        lbl.pack(side="left", padx=14, pady=12)
        col = tk.Frame(f, bg=theme.PANEL)
        col.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(col, text=f"{title}   [{key}]", bg=theme.PANEL, fg=theme.TEXT, font=theme.FONT_BOLD, anchor="w").pack(fill="x")
        tk.Label(col, text=text, bg=theme.PANEL, fg=theme.TEXT_MUTED, font=theme.FONT, anchor="w", justify="left",
                 wraplength=380).pack(fill="x")
        for w in (f, lbl, col, *col.winfo_children()):
            w.bind("<Button-1>", lambda e, m=mode: pick(m))
            w.bind("<Enter>", lambda e, fr=f: fr.configure(highlightbackground=theme.ACCENT))
            w.bind("<Leave>", lambda e, fr=f: fr.configure(highlightbackground=theme.PANEL_BORDER))
        return f

    card(body, "transfer", "Desktop window (GUI)",
         "Use the tool on this laptop. Phones can still connect over Wi-Fi.", "gui", "1")
    card(body, "web", "Web control panel (localhost port)",
         "No window. Open http://<this laptop>:port/admin on your phone, tablet or another PC on the "
         "same Wi-Fi and control everything there. You can close this laptop's screen use.", "web", "2")
    ttk.Checkbutton(body, text="Remember my choice (change it later in Settings > Start-up mode)",
                    variable=remember).pack(anchor="w", pady=(10, 0))

    dlg.bind("<Key-1>", lambda e: pick("gui"))
    dlg.bind("<Key-2>", lambda e: pick("web"))
    dlg.bind("<Return>", lambda e: pick(default if default in ("gui", "web") else "gui"))
    dlg.bind("<Escape>", lambda e: pick(None))
    dlg.protocol("WM_DELETE_WINDOW", lambda: pick(None))

    dlg.update_idletasks()
    w, h = 560, dlg.winfo_reqheight()
    x = (dlg.winfo_screenwidth() - w) // 2
    y = (dlg.winfo_screenheight() - h) // 3
    dlg.geometry(f"{w}x{h}+{x}+{y}")
    dlg.lift()
    dlg.focus_force()
    dlg.grab_set()
    root.wait_window(dlg)
    return result["mode"], result["remember"]

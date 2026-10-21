"""PyDM window: the classic IDM layout in plain tkinter/ttk (light).

Menu bar, icon toolbar, categories tree on the left, one multi-column list, IDM-style dialogs
(Enter new address / Download File Info / Download status / Download complete).
No animation and no per-row widgets: the list is a single ttk.Treeview and only the cells that
really changed are touched, so it stays smooth with hundreds of downloads on a busy network.
"""

import datetime
import os
import queue
import re
import threading
import time
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

if os.name == "nt":                      # crisp text on high-DPI screens (must happen before the first window)
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

try:
    from PIL import Image, ImageTk
except ImportError:                      # icons fall back to tk.PhotoImage (no resizing)
    Image = ImageTk = None

import shell

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(HERE, "icons")
ICO = os.path.join(HERE, "..", "pydm.ico")
CREDIT_URL = "http://asmaadarwish.com/"
CREDIT_TEXT = "Created by Asmaa Darwish - Content Me"
FONT = os.environ.get("PYDM_FONT") or ("Segoe UI" if os.name == "nt" else "DejaVu Sans")

# palettes: classic light, and IDM-like dark
LIGHT = dict(BG="#F0F0F0", WHITE="#FFFFFF", LINE="#D0D0D0", INK="#1A1A1A", MUTED="#606060", LINK="#0645AD", RED="#C00000",
             GREEN="#1E7B34", BLUE="#0B5CAD", SEL="#0078D7", STRIPE="#F4F4F4", HOVER="#E2EEF9", FIELD="#FFFFFF",
             BTN="#E1E1E1", BORDER="#9A9A9A", TRACK="#E6E6E6")
DARK = dict(BG="#2B2B2B", WHITE="#333333", LINE="#4A4A4A", INK="#F0F0F0", MUTED="#A8A8A8", LINK="#7DB7FF", RED="#FF7B7B",
            GREEN="#5CD070", BLUE="#7DB7FF", SEL="#1565C0", STRIPE="#3A3A3A", HOVER="#444444", FIELD="#1F1F1F",
            BTN="#444444", BORDER="#6A6A6A", TRACK="#444444")
DARK_ON = False
BG = WHITE = LINE = INK = MUTED = LINK = RED = GREEN = BLUE = SEL = STRIPE = HOVER = FIELD = BTN = BORDER = TRACK = ""


def apply_theme(dark):
    global DARK_ON
    DARK_ON = bool(dark)
    g = globals()
    g.update(DARK if dark else LIGHT)
    _icons.clear()


def dark_titlebar(win):
    """Windows 10/11: dark title bar to match (silently ignored elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        val = ctypes.c_int(1 if DARK_ON else 0)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4)
    except Exception:  # noqa: BLE001
        pass

CATEGORIES = ["Compressed", "Design", "Documents", "Images", "Music", "Programs", "Videos", "General"]
CAT_LABEL = {"General": "Other", "Videos": "Video"}
LABEL_CAT = {v: k for k, v in CAT_LABEL.items()}
RUNNING = ("probing", "downloading", "converting")
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
QUALITIES = [("Best", "best"), ("1080p", "1080"), ("720p", "720"), ("480p", "480"), ("360p", "360"), ("Audio only", "audio")]

_scale = [1.0]
_history = []                            # addresses typed in this session (the Address drop-down)


_icons = {}


def icon(name):
    """Cached PhotoImage from icons/<name>.png, scaled for the screen's DPI."""
    if DARK_ON:                          # brighter tints on the dark background
        if name.startswith("tb_"):
            name = "tbd_" + name[3:]
        elif name in ("s_all", "s_finished", "s_unfinished", "s_startq", "s_folder"):
            name = "sd_" + name[2:]
    img = _icons.get(name)
    if img is None:
        path = os.path.join(ICON_DIR, name + ".png")
        try:
            if Image is not None:
                im = Image.open(path).convert("RGBA")
                if _scale[0] > 1.25:
                    im = im.resize((round(im.width * _scale[0]), round(im.height * _scale[0])), Image.LANCZOS)
                img = ImageTk.PhotoImage(im)
            else:
                img = tk.PhotoImage(file=path)
        except (OSError, tk.TclError):
            img = tk.PhotoImage(width=1, height=1)
        _icons[name] = img
    return img


apply_theme(False)


def cat_of(it):
    return it["category"] if it["category"] in CATEGORIES else "General"


# ---------------------------------------------------------------- formatting
def fmt_size(n):
    """List column: 477.73 MB"""
    if not n or n < 0:
        return ""
    if n < 1024:
        return f"{int(n)} Bytes"
    for u in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or u == "TB":
            return f"{n:.2f} {u}"


def fmt_size3(n):
    """Download status window: 477.734 MB"""
    if n is None or n < 0:
        return ""
    if n < 1024:
        return f"{int(n)} Bytes"
    for u in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or u == "TB":
            return f"{n:.3f} {u}"


def fmt_time(s):
    if s is None:
        return ""
    s = int(max(0, s))
    if s >= 3600:
        return f"{s // 3600} hour {s % 3600 // 60} min {s % 60} sec"
    if s >= 60:
        return f"{s // 60} min {s % 60} sec"
    return f"{s} sec"


def fmt_date(ts):
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%b %d %H:%M:%S %Y") if ts else ""
    except (OverflowError, OSError, ValueError):
        return ""


def short(text, n):
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def clean_error(msg):
    low = (msg or "").lower()
    if not msg:
        return "Failed"
    if "signed-in" in low or "sign in" in low:
        return "Needs a signed-in account. Use the browser extension."
    return short(msg, 120)


# --------------------------------------------------------------- base dialog
class Dialog(tk.Toplevel):
    """Small window, centred over the main one, sized by its content."""

    def __init__(self, app, title, modal=True, min_width=380, owned=True):
        super().__init__(app, bg=BG)
        self.withdraw()
        self.app = app
        self.min_width = min_width
        self.title(title)
        self.resizable(False, False)
        if owned and app.winfo_viewable():
            self.transient(app)
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._modal = modal
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)
        self.after_idle(self._show)

    def _show(self):
        try:
            self.update_idletasks()
            w, h = max(self.min_width, self.winfo_reqwidth()), self.winfo_reqheight()
            if self.app.winfo_viewable():
                x = self.app.winfo_rootx() + max(0, (self.app.winfo_width() - w) // 2)
                y = self.app.winfo_rooty() + max(0, (self.app.winfo_height() - h) // 3)
            else:                            # main window hidden (pop-up mode): centre on the screen
                x = (self.winfo_screenwidth() - w) // 2
                y = (self.winfo_screenheight() - h) // 3
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.deiconify()
            if DARK_ON:
                self.after(30, lambda: dark_titlebar(self))
            if os.name == "nt" and os.path.exists(ICO):
                self.after(200, self._ico)
            if self._modal:
                self.after(40, self._grab)
        except tk.TclError:
            pass

    def _ico(self):
        try:
            self.iconbitmap(ICO)
        except tk.TclError:
            pass

    def _grab(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def buttons(self, *specs, width=14):
        """Right-aligned button row: specs are (text, command[, default])."""
        bar = tk.Frame(self.body, bg=BG)
        bar.pack(side="bottom", fill="x", padx=12, pady=(8, 12))
        out = []
        for spec in reversed(specs):
            b = ttk.Button(bar, text=spec[0], command=spec[1], width=width)
            b.pack(side="right", padx=(6, 0))
            out.append(b)
            if len(spec) > 2 and spec[2]:
                self.bind("<Return>", lambda e, f=spec[1]: f())
        return out[::-1]


# -------------------------------------------------------------------- dialogs
class AddURL(Dialog):
    """IDM's 'Enter new address to download'."""

    def __init__(self, app, prefill=""):
        super().__init__(app, "Enter new address to download", min_width=560)
        b = self.body
        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", padx=14, pady=(18, 18))
        tk.Label(row, text="Address", bg=BG, fg=INK).pack(side="left")
        self.entry = ttk.Combobox(row, values=_history[:15], width=58)
        self.entry.pack(side="left", fill="x", expand=True, padx=(10, 12))
        side = tk.Frame(row, bg=BG)
        side.pack(side="left")
        ttk.Button(side, text="OK", width=10, command=self.ok).pack()
        ttk.Button(side, text="Cancel", width=10, command=self.close).pack(pady=(6, 0))
        self.entry.set(prefill)
        self.entry.focus_set()
        self.hint = tk.Label(b, text="", bg=BG, fg=RED, anchor="w")
        self.hint.pack(fill="x", padx=14, pady=(0, 10))
        self.bind("<Return>", lambda e: self.ok())

    def ok(self):
        urls = list(dict.fromkeys(URL_RE.findall(self.entry.get())))
        if not urls:
            self.hint.configure(text="Enter a valid address (http:// or https://)")
            return
        for u in urls:
            if u in _history:
                _history.remove(u)
            _history.insert(0, u)
        self.close()
        if len(urls) == 1:
            FileInfo(self.app, urls[0])
        else:                                   # several links pasted at once: no questions, just start them
            q = self.app.mgr.settings.get("quality", "best")
            for u in urls:
                self.app.mgr.add_item({"url": u, "quality": q, "start_now": True})
            self.app.note(f"Added {len(urls)} links")
            self.app.refresh_soon()


class FileInfo(Dialog):
    """IDM's 'Download File Info': what the link is, where it goes, then Start / Later / Cancel."""

    def __init__(self, app, url, spec_extra=None):
        super().__init__(app, "Download File Info", min_width=600)
        self.url, self.name, self.extra = url, "", spec_extra or {}
        self.root_dir = app.mgr.settings.get("root", "")
        b = self.body
        grid = tk.Frame(b, bg=BG)
        grid.pack(fill="x", padx=14, pady=(14, 0))
        grid.columnconfigure(1, weight=1)
        tk.Label(grid, text="URL", bg=BG, fg=INK).grid(row=0, column=0, sticky="e", padx=(0, 8), pady=3)
        self.e_url = ttk.Entry(grid)
        self.e_url.insert(0, url)
        self.e_url.configure(state="readonly")
        self.e_url.grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
        tk.Label(grid, text="Category", bg=BG, fg=INK).grid(row=1, column=0, sticky="e", padx=(0, 8), pady=3)
        self.cat = ttk.Combobox(grid, values=["Automatic"] + [CAT_LABEL.get(c, c) for c in CATEGORIES], state="readonly", width=24)
        self.cat.set("Automatic")
        self.cat.grid(row=1, column=1, sticky="w", pady=3)
        self.cat.bind("<<ComboboxSelected>>", lambda e: self.recalc())
        self.size_l = tk.Label(grid, text="Checking...", bg=BG, fg=MUTED, anchor="w", width=16)
        self.size_l.grid(row=1, column=2, sticky="w", padx=(14, 0))
        tk.Label(grid, text="Save As", bg=BG, fg=INK).grid(row=2, column=0, sticky="e", padx=(0, 8), pady=3)
        self.path = ttk.Entry(grid)
        self.path.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Button(grid, text="...", width=3, command=self.browse).grid(row=2, column=2, sticky="w", padx=(6, 0))
        tk.Label(grid, text="Video quality", bg=BG, fg=INK).grid(row=3, column=0, sticky="e", padx=(0, 8), pady=3)
        self.q = dict(QUALITIES)
        self.menu = ttk.Combobox(grid, values=[n for n, _ in QUALITIES], state="readonly", width=24)
        cur = app.mgr.settings.get("quality", "best")
        self.menu.set(next((n for n, v in QUALITIES if v == cur), "Best"))
        self.menu.grid(row=3, column=1, sticky="w", pady=3)
        self.buttons(("Start Download", lambda: self.go(True), True), ("Download Later", lambda: self.go(False)),
                     ("Cancel", self.close), width=16)
        self.recalc()
        threading.Thread(target=self._probe, daemon=True).start()

    def _probe(self):
        info = shell.probe(self.url)
        self.app.calls.put(lambda: self._probed(info))

    def _probed(self, info):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self.name = info["name"]
        self.size_l.configure(text=fmt_size(info["size"]) if info["size"] else ("Web page" if info["page"] else ""))
        self.recalc()

    def chosen_cat(self):
        label = self.cat.get()
        return "" if label == "Automatic" else LABEL_CAT.get(label, label)

    def default_folder(self):
        cat = self.chosen_cat() or (shell.category_for(self.name) if self.name else "")
        return os.path.join(self.root_dir, cat) if cat else self.root_dir

    def recalc(self):
        self.path.delete(0, "end")
        folder = self.default_folder()
        self.path.insert(0, os.path.join(folder, self.name) if self.name else folder + os.sep)
        self.default_path = self.path.get()

    def browse(self):
        cur = self.path.get()
        got = filedialog.asksaveasfilename(parent=self, initialdir=os.path.dirname(cur) or None,
                                           initialfile=os.path.basename(cur) or self.name or "")
        if got:
            self.path.delete(0, "end")
            self.path.insert(0, os.path.normpath(got))

    def go(self, start):
        spec = dict(self.extra, url=self.url, quality=self.q.get(self.menu.get(), "best"), start_now=start)
        cat = self.chosen_cat()
        if cat:
            spec["category"] = cat
        typed = self.path.get().strip()
        if typed and typed != self.default_path:
            folder, fname = os.path.split(typed)
            if folder and os.path.normpath(folder) != os.path.normpath(self.default_folder()):
                spec["save_dir"] = os.path.normpath(folder)
            if fname and fname != self.name:
                spec["filename"] = fname
        self.app.mgr.add_item(spec)
        self.app.note("Added 1 link")
        self.close()
        self.app.refresh_soon()


class ProgressDialog(Dialog):
    """IDM's 'Download status' window: numbers, one bar, and progress by connections."""

    def __init__(self, app, dl_id):
        super().__init__(app, "Download", modal=False, min_width=540)
        self.id = dl_id
        self.lbl = {}
        self._job = None
        self._last = None
        self.details = True
        nb = ttk.Notebook(self.body)
        nb.pack(fill="x", padx=10, pady=(10, 0))
        tab = tk.Frame(nb, bg=WHITE)
        nb.add(tab, text="Download status")
        self.url_l = tk.Label(tab, text="", bg=WHITE, fg=INK, anchor="w")
        self.url_l.pack(fill="x", padx=12, pady=(12, 6))
        grid = tk.Frame(tab, bg=WHITE)
        grid.pack(fill="x", padx=12, pady=(0, 10))
        for i, key in enumerate(("Status", "File size", "Downloaded", "Transfer rate", "Time left", "Resume capability")):
            tk.Label(grid, text=key, bg=WHITE, fg=INK, anchor="w", width=17).grid(row=i, column=0, sticky="w", pady=1)
            l = tk.Label(grid, text="", bg=WHITE, fg=INK, anchor="w")
            l.grid(row=i, column=1, sticky="w")
            self.lbl[key] = l
        self.bar = tk.Canvas(self.body, height=16, bg=TRACK, highlightthickness=1, highlightbackground=BORDER, bd=0)
        self.bar.pack(fill="x", padx=10, pady=(10, 0))
        self.bar.bind("<Configure>", lambda e: self._redraw())
        self.conn_frame = tk.Frame(self.body, bg=BG)
        tk.Label(self.conn_frame, text="Start positions and download progress by connections", bg=BG, fg=INK).pack(pady=(8, 2))
        self.seg = tk.Canvas(self.conn_frame, height=12, bg=TRACK, highlightthickness=1, highlightbackground=BORDER, bd=0)
        self.seg.pack(fill="x", padx=10)
        self.seg.bind("<Configure>", lambda e: self._redraw())
        self.conn = ttk.Treeview(self.conn_frame, columns=("n", "got", "info"), show="headings", height=6, selectmode="none")
        for c, t, w in (("n", "N.", 40), ("got", "Downloaded", 130), ("info", "Info", 300)):
            self.conn.heading(c, text=t, anchor="w")
            self.conn.column(c, width=w, anchor="w", stretch=(c == "info"))
        self.conn.pack(fill="both", expand=True, padx=10, pady=(8, 0))
        bar = tk.Frame(self.body, bg=BG)
        bar.pack(side="bottom", fill="x", padx=10, pady=(10, 12))
        self.b_details = ttk.Button(bar, text="<< Hide details", command=self.toggle_details, width=16)
        self.b_details.pack(side="left")
        self.b_close = ttk.Button(bar, text="Cancel", command=self.cancel, width=12)
        self.b_close.pack(side="right")
        self.b_main = ttk.Button(bar, text="Pause", command=self.toggle, width=12)
        self.b_main.pack(side="right", padx=8)
        self.conn_frame.pack(fill="both", expand=True, before=bar)
        self.refresh()
        self.after(80, self._front)

    def _front(self):
        """A new status window comes up above everything, like IDM's."""
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.after(600, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    def toggle_details(self):
        self.details = not self.details
        if self.details:
            self.conn_frame.pack(fill="both", expand=True, before=self.b_details.master)
            self.b_details.configure(text="<< Hide details")
        else:
            self.conn_frame.pack_forget()
            self.b_details.configure(text="Show details >>")
        self.update_idletasks()
        try:
            self.geometry(f"{self.winfo_width()}x{self.winfo_reqheight()}")
        except tk.TclError:
            pass

    def toggle(self):
        row = self.app.rows_data.get(self.id)
        if not row:
            return
        if row["status"] in RUNNING or row["status"] == "queued":
            self.app.mgr.pause(self.id)
        else:
            self.app.mgr.resume(self.id)
        self.app.refresh_soon()

    def cancel(self):
        row = self.app.rows_data.get(self.id)
        if row and row["status"] in RUNNING + ("queued",):
            self.app.mgr.pause(self.id)
            self.app.refresh_soon()
        self.close()

    def close(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
        self.app.progress_windows.pop(self.id, None)
        super().close()

    def refresh(self):
        try:
            if not self.winfo_exists():
                return
            row = self.app.rows_data.get(self.id)
            if not row or row["status"] == "completed":        # finished: the 'Download complete' window takes over
                return self.close()
            self._paint(row)
        except tk.TclError:
            return
        self._job = self.after(500, self.refresh)

    def _paint(self, row):
        pct = row["done"] / row["size"] if row["size"] else 0
        st = row["status"]
        self.title(f"{pct * 100:.0f}% {short(row['name'], 50)}" if st in RUNNING and row["size"] else short(row["name"] or "Download", 60))
        self.url_l.configure(text=short(row["url"], 80))
        text = {"downloading": "Receiving data...", "probing": "Finding the video...", "converting": "Converting...",
                "queued": "Waiting", "paused": "Paused", "error": clean_error(row["error"])}[st]
        self.lbl["Status"].configure(text=text, fg=RED if st == "error" else BLUE)
        self.lbl["File size"].configure(text=fmt_size3(row["size"]) if row["size"] else "Unknown")
        self.lbl["Downloaded"].configure(text=f"{fmt_size3(row['done'])}  ( {pct * 100:.2f} % )" if row["size"] else fmt_size3(row["done"]))
        self.lbl["Transfer rate"].configure(text=f"{fmt_size3(row['speed'])}/sec" if row["speed"] > 1 else "")
        self.lbl["Time left"].configure(text=fmt_time(row["eta"]))
        self.lbl["Resume capability"].configure(text="Yes" if row["resumable"] else "No" if row["size"] else "")
        self.b_main.configure(text="Pause" if st in RUNNING or st == "queued" else "Resume")
        self._last = row
        self._redraw()
        if self.details:
            segs = row["segments"] or []
            have = set(self.conn.get_children())
            for i, (s, e, pos) in enumerate(segs, 1):
                iid = str(i)
                vals = (i, fmt_size3(max(0, pos - s)) or "0 Bytes", "Complete" if pos > e else "Receiving data...")
                if iid in have:
                    self.conn.item(iid, values=vals)
                else:
                    self.conn.insert("", "end", iid=iid, values=vals)
            for iid in have:
                if int(iid) > len(segs):
                    self.conn.delete(iid)

    def _redraw(self):
        row = self._last
        self.bar.delete("all")
        self.seg.delete("all")
        if not row:
            return
        size = row["size"]
        w, h = max(10, self.bar.winfo_width() - 2), max(4, self.bar.winfo_height() - 2)
        if size and row["done"]:
            self.bar.create_rectangle(0, 0, min(1, row["done"] / size) * w, h + 1, fill="#2EAD3F", width=0)
        sw, sh = max(10, self.seg.winfo_width() - 2), max(4, self.seg.winfo_height() - 2)
        if size and row["segments"]:
            for s, e, pos in row["segments"]:
                x0, x1 = s / size * sw, min(pos, e + 1) / size * sw
                if x1 > x0:
                    self.seg.create_rectangle(x0, 0, x1, sh + 1, fill="#3B6FD4", width=0)
                self.seg.create_line(x0 + 1, 0, x0 + 1, sh + 1, fill="#D02020")
        elif size and row["done"]:
            self.seg.create_rectangle(0, 0, min(1, row["done"] / size) * sw, sh + 1, fill="#3B6FD4", width=0)


class CompleteDialog(Dialog):
    """IDM's 'Download complete' window."""

    def __init__(self, app, row):
        super().__init__(app, "Download complete", modal=False, min_width=460, owned=False)
        self.row = row
        self.attributes("-topmost", True)
        b = self.body
        top = tk.Frame(b, bg=BG)
        top.pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(top, image=icon("tb_open"), bg=BG).pack(side="left", padx=(0, 10))
        txt = tk.Frame(top, bg=BG)
        txt.pack(side="left")
        tk.Label(txt, text="Download complete", bg=BG, fg=INK, anchor="w").pack(fill="x")
        size = row["size"] or row["done"]
        tk.Label(txt, text=f"Downloaded {fmt_size(size)} ({int(size)} Bytes)" if size else "Downloaded", bg=BG, fg=INK, anchor="w").pack(fill="x")
        for label, value in (("Address", row["url"]), ("The file saved as", row["path"])):
            tk.Label(b, text=label, bg=BG, fg=INK, anchor="w").pack(fill="x", padx=14, pady=(8, 2))
            e = ttk.Entry(b)
            e.insert(0, value)
            e.configure(state="readonly")
            e.pack(fill="x", padx=14)
        bar = tk.Frame(b, bg=BG)
        bar.pack(fill="x", padx=14, pady=(14, 0))
        for text, fn in (("Open", lambda: shell.open_path(row["path"])), ("Open with...", lambda: shell.open_with(row["path"])),
                         ("Open folder", lambda: shell.reveal(row["path"])), ("Close", self.close)):
            ttk.Button(bar, text=text, command=fn, width=13).pack(side="left", padx=(0, 8))
        self.once = tk.BooleanVar(value=False)
        ttk.Checkbutton(b, text="Don't show this dialog again", variable=self.once).pack(anchor="w", padx=14, pady=(12, 14))

    def close(self):
        if self.once.get():
            self.app.mgr.set_settings(notify=False)
        super().close()


class Toast(tk.Toplevel):
    """Small corner notice: 'Added to PyDM' while the window is minimised."""

    def __init__(self, app, title, name, actions=(), seconds=9):
        super().__init__(app, bg=BORDER)
        self.withdraw()                      # shown only once it is placed (no flash in the top-left corner)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        frame = tk.Frame(self, bg=WHITE)
        frame.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(frame, text=title, bg=WHITE, fg=BLUE, font=(FONT, 9, "bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(frame, text=short(name, 44), bg=WHITE, fg=INK, anchor="w").pack(fill="x", padx=12, pady=(0, 6))
        if actions:
            row = tk.Frame(frame, bg=WHITE)
            row.pack(fill="x", padx=8, pady=(0, 10))
            for label, fn in actions:
                ttk.Button(row, text=label, width=11, command=lambda f=fn: (f(), self._bye())).pack(side="left", padx=3)
        else:
            tk.Frame(frame, height=6, bg=WHITE).pack()
        self.after(20, self._place)
        self.after(int(seconds * 1000), self._bye)

    def _place(self):
        try:
            self.update_idletasks()
            w, h = max(300, self.winfo_reqwidth()), self.winfo_reqheight()
            x = self.winfo_screenwidth() - w - 20
            y = self.winfo_screenheight() - h - 70
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.deiconify()
        except tk.TclError:
            pass

    def _bye(self):
        try:
            self.destroy()
        except tk.TclError:
            pass


class UpdateDialog(Dialog):
    def __init__(self, app, status):
        super().__init__(app, "PyDM update", min_width=420, owned=app.winfo_viewable())
        tk.Label(self.body, text=f"PyDM {status.get('latest', '')} is available", bg=BG, fg=INK,
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x", padx=14, pady=(16, 2))
        tk.Label(self.body, text=f"You have {shell.VERSION}." + (("\n" + status["notes"]) if status.get("notes") else ""),
                 bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=380).pack(fill="x", padx=14)
        url = status.get("url") or shell.RELEASES_URL
        self.buttons(("Download", lambda: (webbrowser.open_new_tab(url), self.close()), True), ("Later", self.close))


class Batch(Dialog):
    """Add batch download: one link per line."""

    def __init__(self, app, text=""):
        super().__init__(app, "Add batch download", min_width=520)
        tk.Label(self.body, text="Paste the addresses, one per line", bg=BG, fg=INK, anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        self.text = tk.Text(self.body, width=70, height=10, relief="solid", bd=1, font=(FONT, 9), bg=FIELD, fg=INK, insertbackground=INK)
        self.text.pack(fill="both", expand=True, padx=14)
        self.text.insert("1.0", text)
        self.text.focus_set()
        self.hint = tk.Label(self.body, text="", bg=BG, fg=RED, anchor="w")
        self.hint.pack(fill="x", padx=14)
        self.later = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="Download later (add to the queue)", variable=self.later).pack(anchor="w", padx=14, pady=(2, 0))
        self.buttons(("OK", self.ok), ("Cancel", self.close))

    def ok(self):
        urls = list(dict.fromkeys(URL_RE.findall(self.text.get("1.0", "end"))))
        if not urls:
            self.hint.configure(text="No valid address found")
            return
        q = self.app.mgr.settings.get("quality", "best")
        for u in urls:
            self.app.mgr.add_item({"url": u, "quality": q, "start_now": not self.later.get()})
        self.app.note(f"Added {len(urls)} link{'s' if len(urls) > 1 else ''}")
        self.close()
        self.app.refresh_soon()


class Find(Dialog):
    def __init__(self, app):
        super().__init__(app, "Find", modal=False, min_width=380)
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", padx=14, pady=(16, 14))
        tk.Label(row, text="Find what", bg=BG, fg=INK).pack(side="left")
        self.entry = ttk.Entry(row, width=30)
        self.entry.pack(side="left", padx=8, fill="x", expand=True)
        self.entry.insert(0, app.find_text)
        self.entry.focus_set()
        ttk.Button(row, text="Find Next", width=11, command=self.go).pack(side="left")
        self.bind("<Return>", lambda e: self.go())

    def go(self):
        self.app.find_text = self.entry.get()
        self.app.find_next()


class Scheduler(Dialog):
    def __init__(self, app):
        super().__init__(app, "Scheduler", min_width=380)
        m = app.mgr
        b = self.body
        tk.Label(b, text="Main download queue", bg=BG, fg=INK, font=(FONT, 9, "bold"), anchor="w").pack(fill="x", padx=14, pady=(14, 2))
        tk.Label(b, text="Start the waiting downloads at (PyDM must still be running).", bg=BG, fg=MUTED, anchor="w").pack(fill="x", padx=14)
        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", padx=14, pady=(12, 0))
        now = m.start_at or datetime.datetime.now() + datetime.timedelta(hours=1)
        self.hh = ttk.Spinbox(row, from_=0, to=23, width=4, format="%02.0f", wrap=True, justify="center")
        self.mm = ttk.Spinbox(row, from_=0, to=59, width=4, format="%02.0f", wrap=True, justify="center")
        self.hh.set(f"{now.hour:02d}")
        self.mm.set(f"{now.minute:02d}")
        self.hh.pack(side="left")
        tk.Label(row, text=" : ", bg=BG, fg=INK).pack(side="left")
        self.mm.pack(side="left")
        self.note = tk.Label(b, text=(f"Scheduled for {m.start_at:%H:%M}" if m.start_at else "Not scheduled"),
                             bg=BG, fg=BLUE if m.start_at else MUTED, anchor="w")
        self.note.pack(fill="x", padx=14, pady=(12, 0))
        self.buttons(("Apply", self.apply, True), ("Start now", self.start_now), ("Clear", self.clear), ("Close", self.close))

    def apply(self):
        try:
            hh, mm = int(float(self.hh.get())), int(float(self.mm.get()))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError):
            self.note.configure(text="Enter a time like 02:30", fg=RED)
            return
        self.app.mgr.schedule(f"{hh:02d}:{mm:02d}")
        self.app.refresh_soon()
        self.close()

    def clear(self):
        self.app.mgr.schedule(None)
        self.app.refresh_soon()
        self.close()

    def start_now(self):
        self.app.mgr.set_queue(True)
        self.app.refresh_soon()
        self.close()


class Options(Dialog):
    def __init__(self, app, tab=0):
        super().__init__(app, "PyDM Configuration", min_width=560)
        self.s = app.mgr.settings
        self.nb = ttk.Notebook(self.body)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.tabs = {}
        for name in ("General", "Save to", "Downloads", "Browser", "About"):
            f = tk.Frame(self.nb, bg=WHITE)
            self.nb.add(f, text=name)
            self.tabs[name] = f
        self._general(self.tabs["General"])
        self._saveto(self.tabs["Save to"])
        self._downloads(self.tabs["Downloads"])
        self._browser(self.tabs["Browser"])
        self._about(self.tabs["About"])
        self.nb.select(tab)
        self.buttons(("OK", self.ok, True), ("Cancel", self.close))

    def _row(self, parent, label, help_=None):
        row = tk.Frame(parent, bg=WHITE)
        row.pack(fill="x", padx=14, pady=6)
        box = tk.Frame(row, bg=WHITE)
        box.pack(side="left", fill="x", expand=True)
        tk.Label(box, text=label, bg=WHITE, fg=INK, anchor="w").pack(fill="x")
        if help_:
            tk.Label(box, text=help_, bg=WHITE, fg=MUTED, anchor="w", font=(FONT, 8)).pack(fill="x")
        return row

    def _general(self, tab):
        self.v_autostart = tk.BooleanVar(value=bool(self.s.get("autostart")))
        self.v_notify = tk.BooleanVar(value=bool(self.s.get("notify", True)))
        self.v_dark = tk.BooleanVar(value=self.s.get("theme") == "dark")
        row = self._row(tab, "Dark mode")
        ttk.Checkbutton(row, variable=self.v_dark).pack(side="right")
        if os.name == "nt":
            row = self._row(tab, "Launch PyDM on startup", "Runs quietly so the browser extension always works")
            ttk.Checkbutton(row, variable=self.v_autostart).pack(side="right")
        row = self._row(tab, "Show a dialog when a download finishes")
        ttk.Checkbutton(row, variable=self.v_notify).pack(side="right")

    def _saveto(self, tab):
        self.v_root = tk.StringVar(value=self.s.get("root", ""))
        row = self._row(tab, "Save downloads to", "Files are sorted into a folder per category inside it")
        row = tk.Frame(tab, bg=WHITE)
        row.pack(fill="x", padx=14)
        ttk.Entry(row, textvariable=self.v_root).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self.browse, width=10).pack(side="left", padx=(8, 0))

    def _downloads(self, tab):
        self.v_conc = tk.IntVar(value=int(self.s.get("max_concurrent", 3)))
        self.v_conn = tk.IntVar(value=int(self.s.get("connections", 8)))
        row = self._row(tab, "Downloads at once", "The rest wait for a free slot (1 - 10)")
        ttk.Spinbox(row, from_=1, to=10, width=5, textvariable=self.v_conc).pack(side="right")
        row = self._row(tab, "Maximum connections per file", "More parts means a faster file (1 - 32)")
        ttk.Spinbox(row, from_=1, to=32, width=5, textvariable=self.v_conn).pack(side="right")
        row = self._row(tab, "Default video quality")
        self.q_menu = ttk.Combobox(row, values=[n for n, _ in QUALITIES], state="readonly", width=12)
        self.q_menu.set(next((n for n, v in QUALITIES if v == self.s.get("quality", "best")), "Best"))
        self.q_menu.pack(side="right")

    def browse(self):
        path = filedialog.askdirectory(initialdir=self.v_root.get() or None, parent=self)
        if path:
            self.v_root.set(os.path.normpath(path))

    def _browser(self, tab):
        tk.Label(tab, text="Catch videos that have no link", bg=WHITE, fg=INK, font=(FONT, 10, "bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(12, 2))
        tk.Label(tab, text="Adds a Download button on any page with a video, even course players you're signed in to.",
                 bg=WHITE, fg=MUTED, anchor="w", justify="left", wraplength=500).pack(fill="x", padx=14)
        steps = ["Open  chrome://extensions  in Google Chrome",
                 "Turn on Developer mode (top corner of that page)",
                 "Click Load unpacked and pick the folder below",
                 "Pin PyDM from the puzzle icon in the toolbar"]
        for i, t in enumerate(steps, 1):
            tk.Label(tab, text=f"{i}.  {t}", bg=WHITE, fg=INK, anchor="w").pack(fill="x", padx=18, pady=2)
        box = tk.Frame(tab, bg=WHITE)
        box.pack(fill="x", padx=14, pady=(10, 0))
        e = ttk.Entry(box)
        e.insert(0, shell.EXT_DIR)
        e.configure(state="readonly")
        e.pack(side="left", fill="x", expand=True)
        ttk.Button(box, text="Copy", width=7, command=lambda: self._copy(shell.EXT_DIR)).pack(side="left", padx=(6, 0))
        ttk.Button(box, text="Open folder", width=12, command=lambda: shell.open_path(shell.EXT_DIR)).pack(side="left", padx=(6, 0))
        tk.Label(tab, text="Chrome shows a Developer mode notice for extensions loaded this way. That is normal.",
                 bg=WHITE, fg=MUTED, anchor="w", font=(FONT, 8)).pack(fill="x", padx=14, pady=(8, 10))

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _about(self, tab):
        tk.Label(tab, text=f"PyDM {shell.VERSION}", bg=WHITE, fg=INK, font=(FONT, 13, "bold"), anchor="w").pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(tab, text="Segmented downloads, pause and resume, queue, and video from any page.", bg=WHITE, fg=MUTED,
                 anchor="w").pack(fill="x", padx=14)
        self.eng = tk.Label(tab, text="Video engine " + (shell.ytdlp_version() or "not installed"), bg=WHITE, fg=INK, anchor="w")
        self.eng.pack(fill="x", padx=14, pady=(14, 4))
        self.upd = ttk.Button(tab, text="Update video engine", command=self.update_engine, width=22)
        self.upd.pack(anchor="w", padx=14)
        ttk.Separator(tab).pack(fill="x", padx=14, pady=16)
        ttk.Button(tab, text="Quit PyDM", command=self.app.quit_service, width=14).pack(anchor="w", padx=14)
        tk.Label(tab, text="Quits completely, including the tray. Unfinished downloads continue next time.", bg=WHITE, fg=MUTED,
                 anchor="w", font=(FONT, 8)).pack(fill="x", padx=14, pady=(6, 12))

    def update_engine(self):
        self.upd.configure(text="Updating...", state="disabled")

        def work():
            try:
                v = self.app.mgr.update_engine()
                msg = f"Video engine {v}" if v else "Couldn't update. Check your internet connection."
            except Exception:  # noqa: BLE001
                msg = "Couldn't update. Check your internet connection."
            self.app.calls.put(lambda: (self.eng.configure(text=msg), self.upd.configure(text="Update video engine", state="normal"))
                               if self.winfo_exists() else None)
        threading.Thread(target=work, daemon=True).start()

    def ok(self):
        def num(var, lo, hi, default):
            try:
                return max(lo, min(hi, int(var.get())))
            except (tk.TclError, ValueError):
                return default
        kw = dict(root=self.v_root.get().strip() or self.s.get("root", ""),
                  max_concurrent=num(self.v_conc, 1, 10, 3), connections=num(self.v_conn, 1, 32, 8),
                  quality=dict(QUALITIES).get(self.q_menu.get(), "best"), notify=bool(self.v_notify.get()),
                  theme="dark" if self.v_dark.get() else "light")
        if os.name == "nt":
            kw["autostart"] = bool(self.v_autostart.get())
        self.app.mgr.set_settings(**kw)
        want = kw["theme"] == "dark"
        self.close()
        if want != DARK_ON:
            self.app.after(50, lambda: self.app.set_theme(want))


class ConfirmDelete(Dialog):
    def __init__(self, app, ids):
        super().__init__(app, "Confirm", min_width=420)
        self.ids = ids
        n = len(ids)
        tk.Label(self.body, text=f"Do you want to delete {n} file{'s' if n > 1 else ''} from the list?", bg=BG, fg=INK,
                 anchor="w").pack(fill="x", padx=14, pady=(16, 6))
        self.files = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="Also delete the file(s) from the disk", variable=self.files).pack(anchor="w", padx=14)
        self.buttons(("Yes", self.go, True), ("No", self.close))

    def go(self):
        for i in self.ids:
            self.app.mgr.remove(i, bool(self.files.get()))
        self.close()
        self.app.refresh_soon()


# ------------------------------------------------------------------- main window
class MainWindow(tk.Tk):
    COLS = (("q", "Q", 26, "center"), ("size", "Size", 78, "w"), ("status", "Status", 100, "w"),
            ("left", "Time left", 90, "w"), ("speed", "Transfer rate", 96, "w"),
            ("date", "Last try date", 150, "w"), ("desc", "Description", 110, "w"))

    def __init__(self, mgr, popup=None):
        self.mgr = mgr                       # remote.Remote: the window never touches the engine directly
        super().__init__()
        self.popup_only = popup is not None  # started only to show a progress / "complete" window
        self.popup = popup or {}
        if self.popup_only:
            self.withdraw()
        self.idle_since = time.time()
        _scale[0] = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.configure(bg=BG)
        self.title("PyDM")
        self.geometry("1100x620")
        self.minsize(760, 400)
        self.calls = queue.Queue()
        self.rows_data, self.order, self.cache = {}, [], {}
        self.filter = "all"
        self.sort_col, self.sort_rev = "added", True
        self.status_note, self.note_until = "", 0.0
        self.prev_status, self.popped = {}, set()
        self.first_tick = True
        self.progress_windows = {}
        self.seen_seq = None
        self.cats_on = True
        self.find_text = ""
        self.dark_applied = None
        self.style_it()
        self.build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-v>", self.on_paste)
        self.bind("<Delete>", lambda e: self.delete_selected())
        self.bind("<Control-a>", self.select_all)
        self.bind("<Control-n>", lambda e: self.add_dialog())
        self.bind("<Control-f>", lambda e: Find(self))
        self.bind("<F3>", lambda e: self.find_next())
        self._set_icon()
        if DARK_ON:
            self.after(300, lambda: dark_titlebar(self))
        self.after(100, self.pump)
        self.after(150, self.tick)
        if not self.popup_only:
            self.after(4000, lambda: self.check_updates(False))

    def _set_icon(self):
        try:
            if os.name == "nt" and os.path.exists(ICO):
                self.after(200, lambda: self.iconbitmap(ICO))
            else:
                self._logo = tk.PhotoImage(file=os.path.join(ICON_DIR, "logo.png"))
                self.iconphoto(True, self._logo)
        except tk.TclError:
            pass

    def style_it(self):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            try:
                tkfont.nametofont(name).configure(family=FONT, size=9)
            except tk.TclError:
                pass
        st = ttk.Style(self)
        native = os.name == "nt" and "vista" in st.theme_names() and not DARK_ON
        st.theme_use("vista" if native else "clam")
        row_h = tkfont.nametofont("TkDefaultFont").metrics("linespace") + 7
        if DARK_ON or not native:            # clam / dark: set every colour ourselves
            st.configure(".", background=BG, foreground=INK, fieldbackground=FIELD, bordercolor=BORDER, lightcolor=BG,
                         darkcolor=BG, troughcolor=BG, focuscolor=BG, insertcolor=INK, selectbackground=SEL,
                         selectforeground="#FFFFFF")
            st.configure("TButton", background=BTN, foreground=INK, bordercolor=BORDER, padding=(6, 3), relief="flat")
            st.map("TButton", background=[("active", HOVER), ("pressed", BORDER), ("disabled", BG)],
                   foreground=[("disabled", MUTED)])
            st.configure("TEntry", fieldbackground=FIELD, foreground=INK, bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD)
            st.map("TEntry", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)])
            st.configure("TCombobox", fieldbackground=FIELD, background=BTN, foreground=INK, arrowcolor=INK, bordercolor=BORDER,
                         lightcolor=FIELD, darkcolor=FIELD)
            st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)],
                   selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
            st.configure("TSpinbox", fieldbackground=FIELD, background=BTN, foreground=INK, arrowcolor=INK, bordercolor=BORDER)
            st.configure("TCheckbutton", background=BG, foreground=INK, indicatorbackground=FIELD, indicatorforeground=INK)
            st.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", SEL)])
            st.configure("TNotebook", background=BG, bordercolor=BORDER, lightcolor=BG, darkcolor=BG)
            st.configure("TNotebook.Tab", background=BTN, foreground=INK, padding=(8, 3), bordercolor=BORDER, lightcolor=BTN, darkcolor=BTN)
            st.map("TNotebook.Tab", background=[("selected", WHITE)], lightcolor=[("selected", WHITE)])
            st.configure("TScrollbar", background=BORDER, troughcolor=FIELD, bordercolor=BG, arrowcolor=INK, lightcolor=BTN, darkcolor=BTN)
            for sb in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
                thumb, trough = ("#6A6A6A", "#262626") if DARK_ON else ("#C2C2C2", "#F0F0F0")
                st.configure(sb, background=thumb, troughcolor=trough, bordercolor=trough, arrowcolor=INK,
                             lightcolor=thumb, darkcolor=thumb, gripcount=0)
                st.map(sb, background=[("active", "#8A8A8A" if DARK_ON else "#A8A8A8"), ("pressed", "#8A8A8A" if DARK_ON else "#A8A8A8")])
            st.configure("TPanedwindow", background=BG)
            st.configure("TSeparator", background=LINE)
            st.configure("Treeview.Heading", background=BTN, foreground=INK, bordercolor=BORDER, lightcolor=BTN, darkcolor=BTN, relief="flat")
            st.map("Treeview.Heading", background=[("active", HOVER)])
            self.option_add("*TCombobox*Listbox.background", FIELD)
            self.option_add("*TCombobox*Listbox.foreground", INK)
            self.option_add("*TCombobox*Listbox.selectBackground", SEL)
            self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        st.configure("Treeview", rowheight=max(row_h, round(18 * _scale[0])), background=WHITE, fieldbackground=WHITE,
                     foreground=INK, borderwidth=0)
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.map("Treeview", background=[("selected", SEL)], foreground=[("selected", "#FFFFFF")])
        st.configure("Treeview.Heading", font=(FONT, 9), padding=(4, 3))
        for opt, val in (("background", BG), ("foreground", INK), ("activeBackground", SEL), ("activeForeground", "#FFFFFF"),
                         ("disabledForeground", MUTED)):
            self.option_add("*Menu." + opt, val)
        self.configure(bg=BG)
        self.dark_applied = DARK_ON

    def set_theme(self, dark):
        """Switch light / dark without restarting: tear the widgets down and build them again."""
        if dark == DARK_ON:
            return
        apply_theme(dark)
        for w in self.winfo_children():
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.progress_windows.clear()
        self.cache, self.order = {}, []
        self.style_it()
        self.build()
        self.after(50, lambda: dark_titlebar(self))
        self.tick(now=True)

    # -- layout
    def build(self):
        self.build_menu()
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x")
        self.tools = {}
        spec = [("add", "Add URL", self.add_dialog), ("resume", "Resume", self.resume_selected),
                ("stop", "Stop", self.stop_selected), ("stopall", "Stop All", self.stop_all),
                ("delete", "Delete", self.delete_selected), ("deletedone", "Delete Co...", self.clear_done),
                ("options", "Options", lambda: Options(self)), ("scheduler", "Scheduler", lambda: Scheduler(self)),
                ("startq", "Start Qu...", lambda: self.queue_cmd(True)), ("stopq", "Stop Qu...", lambda: self.queue_cmd(False))]
        for key, text, cmd in spec:
            b = tk.Button(bar, text=text, image=icon("tb_" + key), compound="top", command=cmd, bg=BG, activebackground=HOVER,
                          fg=INK, activeforeground=INK, disabledforeground=MUTED, relief="flat", overrelief="groove",
                          bd=1, padx=6, pady=3, takefocus=0, cursor="arrow", highlightthickness=0)
            b.pack(side="left", padx=(1, 0 if key in ("startq", "stopq") else 1), pady=3)
            b.key, b.on = key, True
            self.tools[key] = b
            if key in ("startq", "stopq"):                       # IDM's little drop-down next to the queue buttons
                on = key == "startq"
                arrow = tk.Menubutton(bar, text="▾", bg=BG, fg=MUTED, relief="flat", bd=0, padx=2, takefocus=0, activebackground=HOVER)
                arrow.menu = tk.Menu(arrow, tearoff=0)
                arrow.menu.add_command(label="Main download queue", command=lambda on=on: self.queue_cmd(on))
                arrow.configure(menu=arrow.menu)
                arrow.pack(side="left", padx=(0, 6))
        tk.Frame(self, height=1, bg=LINE).pack(fill="x")

        status = tk.Frame(self, bg=BG)
        status.pack(side="bottom", fill="x")
        tk.Frame(status, height=1, bg=LINE).pack(fill="x")
        inner = tk.Frame(status, bg=BG)
        inner.pack(fill="x", padx=8, pady=3)
        self.summary = tk.Label(inner, text="Ready", bg=BG, fg=MUTED, anchor="w")
        self.summary.pack(side="left")
        self.credit = tk.Label(inner, text=CREDIT_TEXT, bg=BG, fg=MUTED, cursor="hand2")
        self.credit.place(relx=0.5, rely=0.5, anchor="center")
        self.credit.bind("<Button-1>", lambda e: webbrowser.open_new_tab(CREDIT_URL))
        self.credit.bind("<Enter>", lambda e: self.credit.configure(fg=LINK, font=(FONT, 9, "underline")))
        self.credit.bind("<Leave>", lambda e: self.credit.configure(fg=MUTED, font=(FONT, 9)))

        self.pane = ttk.PanedWindow(self, orient="horizontal")
        self.pane.pack(fill="both", expand=True, padx=3, pady=3)
        self.side_frame = tk.Frame(self.pane, bg=WHITE, width=190, highlightthickness=1, highlightbackground=BORDER)
        self.build_side(self.side_frame)
        self.pane.add(self.side_frame, weight=0)
        right = tk.Frame(self.pane, bg=WHITE, highlightthickness=1, highlightbackground=BORDER)
        self.pane.add(right, weight=1)
        self.build_list(right)

    def build_menu(self):
        m = tk.Menu(self, tearoff=0)
        self.menu_list = []
        tasks = tk.Menu(m, tearoff=0)
        tasks.add_command(label="Add new download", command=self.add_dialog, accelerator="Ctrl+N")
        tasks.add_command(label="Add batch download", command=lambda: Batch(self))
        tasks.add_command(label="Add batch download from clipboard", command=self.batch_clipboard)
        tasks.add_separator()
        tasks.add_command(label="Quit PyDM completely", command=self.quit_service)
        tasks.add_command(label="Exit", command=self.on_close)
        self.menu_list.append(("Tasks", tasks))
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Stop Download", command=self.stop_selected)
        fm.add_command(label="Remove", command=self.delete_selected)
        fm.add_command(label="Download Now", command=self.download_now)
        self.menu_list.append(("File", fm))
        dl = tk.Menu(m, tearoff=0)
        dl.add_command(label="Stop All", command=self.stop_all)
        dl.add_separator()
        dl.add_command(label="Delete All Completed", command=self.clear_done)
        dl.add_separator()
        dl.add_command(label="Find", command=lambda: Find(self), accelerator="Ctrl-F")
        dl.add_command(label="Find Next", command=self.find_next, accelerator="F3")
        dl.add_separator()
        dl.add_command(label="Scheduler", command=lambda: Scheduler(self))
        start = tk.Menu(dl, tearoff=0)
        start.add_command(label="Main download queue", command=lambda: self.queue_cmd(True))
        dl.add_cascade(label="Start queue", menu=start)
        stop = tk.Menu(dl, tearoff=0)
        stop.add_command(label="Main download queue", command=lambda: self.queue_cmd(False))
        dl.add_cascade(label="Stop queue", menu=stop)
        dl.add_separator()
        dl.add_command(label="Options", command=lambda: Options(self))
        self.menu_list.append(("Downloads", dl))
        view = tk.Menu(m, tearoff=0)
        self.cats_label = "Hide categories"
        view.add_command(label=self.cats_label, command=self.toggle_cats)
        self.view_menu = view
        arr = tk.Menu(view, tearoff=0)
        for label, key in (("Name", "name"), ("Size", "size"), ("Status", "status"), ("Time left", "eta"), ("Last try date", "added")):
            arr.add_command(label=label, command=lambda k=key: self.sort_by(k))
        view.add_cascade(label="Arrange files", menu=arr)
        self.menu_list.append(("View", view))
        helpm = tk.Menu(m, tearoff=0)
        helpm.add_command(label="Browser extension setup", command=lambda: Options(self, 3))
        helpm.add_separator()
        helpm.add_command(label="Check for updates", command=lambda: self.check_updates(True))
        helpm.add_command(label="PyDM Home Page", command=lambda: webbrowser.open_new_tab(CREDIT_URL))
        helpm.add_separator()
        helpm.add_command(label="About PyDM", command=lambda: Options(self, 4))
        self.menu_list.append(("Help", helpm))
        if DARK_ON:                          # the native Windows menu bar can't be dark: draw our own
            bar = tk.Frame(self, bg=BG)
            bar.pack(fill="x")
            for label, sub in self.menu_list:
                b = tk.Label(bar, text=label, bg=BG, fg=INK, padx=9, pady=3, cursor="arrow")
                b.pack(side="left")
                b.bind("<Enter>", lambda e, w=b: w.configure(bg=HOVER))
                b.bind("<Leave>", lambda e, w=b: w.configure(bg=BG))
                b.bind("<Button-1>", lambda e, w=b, m=sub: self.popup_menu(w, m))
            self.configure(menu="")
        else:
            for label, sub in self.menu_list:
                m.add_cascade(label=label, menu=sub, underline=0)
            self.configure(menu=m)

    def check_updates(self, manual):
        """Look for a newer version in the background; tell the user only if there is one (or when asked)."""
        def work():
            st = shell.check_status()
            self.calls.put(lambda: self._updates_done(st, manual))
        threading.Thread(target=work, daemon=True).start()

    def _updates_done(self, st, manual):
        if st.get("latest") and shell.is_newer(st["latest"]):
            if manual or st["latest"] != getattr(self, "update_seen", None):
                self.update_seen = st["latest"]
                UpdateDialog(self, st)
        elif manual:
            self.note("PyDM is up to date" if st else "Couldn't check for updates", 5)

    def popup_menu(self, widget, menu):
        """Drop-down under a label of the dark menu bar (works the same on every platform)."""
        try:
            menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def build_side(self, parent):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Categories", bg=BG, fg=INK, anchor="w").pack(side="left", padx=6, pady=2)
        x = tk.Label(head, text="×", bg=BG, fg=INK, cursor="arrow", padx=5)
        x.pack(side="right")
        x.bind("<Button-1>", lambda e: self.toggle_cats())
        self.side = ttk.Treeview(parent, show="tree", selectmode="browse")
        self.side.pack(fill="both", expand=True)
        self.side.insert("", "end", iid="all", text=" All Downloads", image=icon("s_folder"), open=True)
        for cat in CATEGORIES:
            self.side.insert("all", "end", iid="cat:" + cat, text=" " + CAT_LABEL.get(cat, cat), image=icon("s_cat_" + cat))
        self.side.insert("", "end", iid="unfinished", text=" Unfinished", image=icon("s_unfinished"))
        self.side.insert("", "end", iid="finished", text=" Finished", image=icon("s_finished"))
        self.side.insert("", "end", iid="queues", text=" Queues", image=icon("s_folder"), open=True)
        self.side.insert("queues", "end", iid="queued", text=" Main download queue", image=icon("s_startq"))
        self.side.selection_set("all")
        self.side.bind("<<TreeviewSelect>>", self.on_side)

    def build_list(self, parent):
        cols = [c[0] for c in self.COLS]
        wrap = tk.Frame(parent, bg=WHITE)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=cols, selectmode="extended")
        self.tree.heading("#0", text="File Name", anchor="w", command=lambda: self.sort_by("name"))
        self.tree.column("#0", width=240, minwidth=120, stretch=True)
        keys = {"size": "size", "status": "status", "left": "eta", "speed": "speed", "date": "added", "desc": "desc", "q": "q"}
        for key, title, width, anchor in self.COLS:
            self.tree.heading(key, text=title, anchor="w", command=lambda k=keys[key]: self.sort_by(k))
            self.tree.column(key, width=width, minwidth=24, anchor=anchor, stretch=(key == "desc"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("error", foreground=RED)
        self.tree.tag_configure("stripe", background=STRIPE)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_tools())
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Return>", lambda e: self.on_double(None))
        self.tree.bind("<Button-3>", self.on_right)
        self.menu = tk.Menu(self, tearoff=0)
        for label, fn in (("Open", self.open_selected), ("Open folder", self.folder_selected), (None, None),
                          ("Resume", self.resume_selected), ("Stop Download", self.stop_selected), (None, None),
                          ("Copy address", self.copy_address), ("Remove", self.delete_selected)):
            if label:
                self.menu.add_command(label=label, command=fn)
            else:
                self.menu.add_separator()
        self.empty = tk.Label(wrap, text="No downloads here yet.\nClick Add URL, or copy a link and press Ctrl+V.",
                              bg=WHITE, fg=MUTED, justify="center")

    # -- small helpers
    def toggle_cats(self):
        if self.cats_on:
            self.pane.forget(self.side_frame)
        else:
            self.pane.insert(0, self.side_frame, weight=0)
        self.cats_on = not self.cats_on
        self.view_menu.entryconfigure(0, label="Hide categories" if self.cats_on else "Show categories")

    def queue_cmd(self, on):
        self.mgr.set_queue(on)
        self.refresh_soon()

    def on_side(self, e=None):
        sel = self.side.selection()
        if not sel:
            return
        if sel[0] in ("all", "unfinished", "finished", "queued") or sel[0].startswith("cat:"):
            self.filter = sel[0]
            self.tick(now=True)
        else:                                # the 'Queues' folder row itself
            self.side.selection_set("queued")

    def sort_by(self, key):
        self.sort_rev = not self.sort_rev if key == self.sort_col else key in ("added", "size")
        self.sort_col = key
        self.tick(now=True)

    def refresh_soon(self):
        self.mgr.refresh_soon()
        self.after(250, lambda: self.tick(now=True))

    def selected(self):
        return list(self.tree.selection())

    def apply_tool(self, key, on):
        b = self.tools[key]
        if b.on != on:
            b.on = on
            b.configure(state="normal" if on else "disabled", image=icon("tb_" + key + ("" if on else "_off")))

    def update_tools(self):
        rows = [self.rows_data[i] for i in self.selected() if i in self.rows_data]
        allr = self.rows_data.values()
        self.apply_tool("resume", any(r["status"] in ("paused", "error") for r in rows))
        self.apply_tool("stop", any(r["status"] in RUNNING or r["status"] == "queued" for r in rows))
        self.apply_tool("stopall", any(r["status"] in RUNNING or r["status"] == "queued" for r in allr))
        self.apply_tool("delete", bool(rows))
        self.apply_tool("deletedone", any(r["status"] == "completed" for r in allr))

    # -- thread bridge
    def pump(self):
        try:
            while True:
                self.calls.get_nowait()()
        except queue.Empty:
            pass
        if self.mgr.lost:                    # the service is gone (quit from the tray, or crashed)
            return self.quit_now()
        if self.popup_only:                  # started only for a progress / complete window: leave when they are closed
            try:
                busy = any(isinstance(w, (ProgressDialog, CompleteDialog)) and w.winfo_exists() for w in self.winfo_children())
            except tk.TclError:
                busy = True
            if busy or not self.mgr.ready:
                self.idle_since = time.time()
            elif time.time() - self.idle_since > 4:
                return self.quit_now()
        seq = self.mgr.show_seq
        if seq is not None and seq != self.seen_seq:
            if self.seen_seq is not None:
                self.bring_up()
            self.seen_seq = seq
        self.after(200, self.pump)

    def bring_up(self):
        self.popup_only = False
        self.deiconify()
        self.state("normal")
        self.lift()
        self.attributes("-topmost", True)
        self.after(150, lambda: self.attributes("-topmost", False))
        self.focus_force()
        self.after(60, lambda: self.tick(now=True))

    # -- closing: closing the window only closes the window; downloads keep going in the service
    def on_close(self):
        self.quit_now()

    def quit_service(self):
        threading.Thread(target=self.mgr.quit_service, daemon=True).start()
        self.after(300, self.quit_now)

    def quit_now(self):
        try:
            self.mgr.stop()
            self.destroy()
        except tk.TclError:
            pass

    def note(self, text, seconds=4):
        self.status_note, self.note_until = text, time.time() + seconds

    # -- actions
    def select_all(self, e=None):
        if isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            return
        self.tree.selection_set(self.order)

    def on_right(self, e):
        iid = self.tree.identify_row(e.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.menu.tk_popup(e.x_root, e.y_root)

    def on_double(self, e):
        sel = self.selected()
        if sel:
            self.activate(sel[0])

    def activate(self, dl_id):
        row = self.rows_data.get(dl_id)
        if not row:
            return
        if row["status"] == "completed" and row["path"] and os.path.exists(row["path"]):
            shell.open_path(row["path"])
        else:
            self.show_progress(dl_id)

    def show_progress(self, dl_id):
        w = self.progress_windows.get(dl_id)
        if w is not None and w.winfo_exists():
            w.lift()
            return
        self.progress_windows[dl_id] = ProgressDialog(self, dl_id)

    def open_selected(self):
        for i in self.selected()[:1]:
            row = self.rows_data.get(i)
            if row and row["status"] == "completed" and row["path"] and os.path.exists(row["path"]):
                shell.open_path(row["path"])

    def folder_selected(self):
        for i in self.selected()[:1]:
            row = self.rows_data.get(i)
            if row and row["path"]:
                shell.reveal(row["path"])

    def copy_address(self):
        urls = [self.rows_data[i]["url"] for i in self.selected() if i in self.rows_data]
        if urls:
            self.clipboard_clear()
            self.clipboard_append("\n".join(urls))

    def resume_selected(self):
        for i in self.selected():
            self.mgr.resume(i)
        self.refresh_soon()

    def download_now(self):
        """File > Download Now: resume stopped ones, and push waiting ones to the front."""
        for i in self.selected():
            r = self.rows_data.get(i)
            if not r:
                continue
            if r["status"] in ("paused", "error"):
                self.mgr.resume(i)
            elif r["status"] == "queued":
                self.mgr.pause(i)
                self.after(700, lambda i=i: (self.mgr.resume(i), self.refresh_soon()))
        self.refresh_soon()

    def stop_selected(self):
        for i in self.selected():
            self.mgr.pause(i)
        self.refresh_soon()

    def stop_all(self):
        for r in list(self.rows_data.values()):
            if r["status"] in RUNNING or r["status"] == "queued":
                self.mgr.pause(r["id"])
        self.refresh_soon()

    def delete_selected(self):
        if self.selected() and not isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            ConfirmDelete(self, self.selected())

    def clear_done(self):
        self.mgr.clear_finished()
        self.refresh_soon()

    def add_dialog(self, prefill=""):
        if not prefill:
            try:
                found = URL_RE.findall(self.clipboard_get())
                prefill = " ".join(found[:5]) if found else ""
            except tk.TclError:
                prefill = ""
        AddURL(self, prefill)

    def batch_clipboard(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        urls = list(dict.fromkeys(URL_RE.findall(text)))
        if not urls:
            self.note("No addresses in the clipboard")
            return
        q = self.mgr.settings.get("quality", "best")
        for u in urls:
            self.mgr.add_item({"url": u, "quality": q, "start_now": True})
        self.note(f"Added {len(urls)} link{'s' if len(urls) > 1 else ''}")
        self.refresh_soon()

    def find_next(self):
        text = self.find_text.lower().strip()
        if not text or not self.order:
            return
        cur = self.selected()
        start = self.order.index(cur[0]) + 1 if cur and cur[0] in self.order else 0
        for k in range(len(self.order)):
            i = self.order[(start + k) % len(self.order)]
            r = self.rows_data.get(i)
            if r and (text in (r["name"] or "").lower() or text in r["url"].lower()):
                self.tree.selection_set(i)
                self.tree.see(i)
                return
        self.note("Not found")

    def on_paste(self, e):
        if isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            return
        self.add_dialog()

    # -- refresh
    def tick(self, now=False):
        try:
            self._tick()
        except tk.TclError:
            return
        except Exception:  # noqa: BLE001 - one bad row must never stop the refresh loop
            import traceback
            traceback.print_exc()
        if not now:
            try:
                shown = self.winfo_viewable()
            except tk.TclError:
                return
            busy = self.mgr.active_count() > 0
            self.after(1000 if shown and busy else 1500 if shown else 2500, self.tick)

    @staticmethod
    def cells(it):
        st, size, done = it["status"], it["size"], it["done"]
        pct = done / size if size > 0 else 0
        if st == "error":
            desc = clean_error(it["error"])
        else:
            bits = [it["host"]] if it["host"] else []
            if it.get("media") and it.get("quality") not in (None, "best", "audio"):
                bits.append(it["quality"] + "p")
            desc = "  ·  ".join(bits)
        status = {
            "downloading": f"{pct * 100:.2f}%" if size else "Receiving...",
            "probing": "Finding video..." if it.get("phase") == "finding" else "Checking link...",
            "converting": "Converting...", "queued": "Waiting",
            "paused": f"{pct * 100:.2f}%" if size else "Paused",
            "completed": "Complete", "error": "Failed"}[st]
        return (("•" if st != "completed" else ""), fmt_size(size), status,
                fmt_time(it["eta"]) if st == "downloading" else "",
                f"{fmt_size(it['speed'])}/sec" if st == "downloading" and it["speed"] > 1 else "",
                fmt_date(it.get("added")), desc)

    def _tick(self):
        if not self.mgr.ready:
            return
        rows = self.mgr.snapshot()
        self.rows_data = {r["id"]: r for r in rows}
        viewable = self.winfo_viewable()
        fresh = []
        for r in rows:                       # a download that starts (extension, link, queue) and one that finishes
            rid, st = r["id"], r["status"]
            old = self.prev_status.get(rid)
            if self.first_tick:
                if rid in self.popup.get("add", ()) and st != "completed":
                    fresh.append(r)
                elif rid in self.popup.get("done", ()) and st == "completed" and self.mgr.settings.get("notify", True):
                    CompleteDialog(self, r)
                if rid not in self.popup.get("add", ()):
                    self.popped.add(rid)
            else:
                if st in RUNNING and old not in RUNNING:
                    fresh.append(r)
                elif old in RUNNING + ("queued",) and st == "completed" and self.mgr.settings.get("notify", True):
                    CompleteDialog(self, r)
            if st in RUNNING:
                self.popped.add(rid)
            self.prev_status[rid] = st
        for r in fresh[:3]:                  # IDM shows the status window by itself; never flood on a big batch
            self.show_progress(r["id"])
        self.first_tick = False
        if not viewable:                     # minimised: no drawing, near-zero CPU
            return

        f = self.filter
        shown = [r for r in rows if f == "all" or (f == "finished" and r["status"] == "completed")
                 or (f == "unfinished" and r["status"] != "completed") or (f == "queued" and r["status"] == "queued")
                 or f == "cat:" + cat_of(r)]
        keyf = {"name": lambda r: (r["name"] or r["url"]).lower(), "size": lambda r: r["size"], "status": lambda r: r["status"],
                "eta": lambda r: -1 if r["eta"] is None else r["eta"], "speed": lambda r: r["speed"], "added": lambda r: r.get("added") or 0,
                "desc": lambda r: r["host"], "q": lambda r: r["status"] != "completed"}[self.sort_col]
        shown.sort(key=keyf, reverse=self.sort_rev)
        ids = [r["id"] for r in shown]
        tree = self.tree
        if ids != self.order:
            gone = set(self.order) - set(ids)
            if gone:
                tree.delete(*[i for i in gone if tree.exists(i)])
                for i in gone:
                    self.cache.pop(i, None)
            for pos, r in enumerate(shown):
                if r["id"] not in self.cache:
                    tree.insert("", pos, iid=r["id"], text=" " + short(r["name"] or r["url"], 90),
                                image=icon("r_cat_" + cat_of(r)), values=self.cells(r))
                    self.cache[r["id"]] = None
            if list(tree.get_children()) != ids:
                for pos, i in enumerate(ids):
                    tree.move(i, "", pos)
            self.order = ids
        for pos, r in enumerate(shown):
            cells = self.cells(r)
            sig = (cells, r["name"], cat_of(r), pos % 2)
            if self.cache.get(r["id"]) != sig:
                self.cache[r["id"]] = sig
                tags = (("error",) if r["status"] == "error" else ()) + (("stripe",) if pos % 2 else ())
                tree.item(r["id"], text=" " + short(r["name"] or r["url"], 90), image=icon("r_cat_" + cat_of(r)), values=cells, tags=tags)
        if shown:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")
        self.update_tools()

        run = [r for r in rows if r["status"] in RUNNING]
        speed = sum(r["speed"] for r in rows)
        q = self.mgr
        text = f"{len(run)} downloading   ·   {fmt_size(speed)}/sec" if run else "Ready"
        if q.start_at:
            text += f"   ·   queue starts at {q.start_at:%H:%M}"
        elif q.queue_active:
            text += "   ·   queue running"
        if self.status_note and time.time() < self.note_until:
            text = self.status_note
        self.summary.configure(text=text)

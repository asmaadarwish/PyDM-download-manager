"""Light helpers shared by the service and the window process (keeps the window's start-up fast:
no engine, no http.server imports here)."""

import json
import os
import re
import subprocess
import sys
import urllib.request

VERSION = "3.5.0"
REPO = "asmaadarwish/PyDM-download-manager"
STATUS_URL = os.environ.get("PYDM_STATUS_URL") or f"https://raw.githubusercontent.com/{REPO}/main/status.json"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
HERE = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.path.join(HERE, "extension")
PORT_BASE = int(os.environ.get("PYDM_PORT", "47321"))
PORT_TRIES = 10
USER_LIB = os.path.join(os.path.expanduser("~"), ".pydm", "lib")     # updatable video engine
for _p in (os.path.join(HERE, "lib"), USER_LIB):                      # USER_LIB wins
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


if os.name == "nt":                      # the bundled Python keeps Tcl/Tk's script folders next to it
    _RT = os.path.normpath(os.path.join(HERE, "..", "runtime", "tcl"))
    for _var, _sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
        if os.path.isdir(os.path.join(_RT, _sub)):
            os.environ.setdefault(_var, os.path.join(_RT, _sub))


def home_dir():
    return os.path.join(os.path.expanduser("~"), ".pydm")


def load_token():
    os.makedirs(home_dir(), exist_ok=True)
    path = os.path.join(home_dir(), "token")
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
        if len(tok) >= 16:
            return tok
    except OSError:
        pass
    import secrets
    tok = secrets.token_urlsafe(24)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tok)
    return tok


def ping(port, timeout=0.5):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            d = json.load(r)
        return d if d.get("app") == "pydm" else None
    except (OSError, ValueError):
        return None


def find_running():
    """Port of an already running PyDM, or None."""
    for p in range(PORT_BASE, PORT_BASE + PORT_TRIES):
        if ping(p):
            return p
    return None


def call(port, token, path, body=None, timeout=5):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST",
                                 data=json.dumps(body or {}).encode(),
                                 headers={"X-PyDM-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ------------------------------------------------------------ OS helpers
def open_path(path):
    if os.name == "nt":
        os.startfile(path)                                   # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal(path):
    if os.name == "nt" and os.path.exists(path):
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
    else:
        open_path(os.path.dirname(path) if os.path.exists(path) else path)


CATEGORIES = {   # keep in sync with engine.CATEGORIES (the window must not import the engine)
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".epub", ".csv", ".html", ".htm"},
    "Design": {".psd", ".ai", ".fig", ".sketch", ".indd", ".eps", ".otf", ".ttf"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff"},
    "Compressed": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Programs": {".exe", ".msi", ".dmg", ".apk", ".deb", ".iso", ".pkg"},
}


def category_for(name):
    ext = os.path.splitext(name or "")[1].lower()
    return next((c for c, exts in CATEGORIES.items() if ext in exts), "General")


def open_with(path):
    """Windows 'Open with...' chooser."""
    if os.name == "nt":
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", os.path.normpath(path)])
    else:
        open_path(path)


def probe(url, timeout=8):
    """Ask the server what the link is: {'size': int, 'name': str, 'page': bool}. Never raises."""
    import urllib.parse
    out = {"size": 0, "name": "", "page": False}
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PyDM/1.0"}
    for method, extra in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
        try:
            req = urllib.request.Request(url, method=method, headers=dict(ua, **extra))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                h = r.headers
                ctype = (h.get("Content-Type") or "").lower()
                m = re.search(r"/(\d+)\s*$", h.get("Content-Range") or "")
                size = int(m.group(1)) if m else int(h.get("Content-Length") or 0) if method == "HEAD" else 0
                cd = h.get("Content-Disposition") or ""
                m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd) or re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
                name = urllib.parse.unquote(m.group(1)).strip() if m else ""
                if not name:
                    name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(r.geturl()).path))
                out.update(size=size, name=name, page=ctype.startswith("text/html"))
                if out["page"]:
                    out.update(size=0, name="")
                return out
        except (OSError, ValueError):
            continue
    return out


_ytdlp_ver = None


def ytdlp_version():
    """Read the version from the file instead of importing yt-dlp (that import is slow)."""
    global _ytdlp_ver
    if _ytdlp_ver is None:
        _ytdlp_ver = ""
        try:
            import importlib.util
            spec = importlib.util.find_spec("yt_dlp")
            with open(os.path.join(os.path.dirname(spec.origin), "version.py"), encoding="utf-8") as f:
                m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", f.read())
            _ytdlp_ver = m.group(1) if m else ""
        except Exception:  # noqa: BLE001
            pass
    return _ytdlp_ver


# ------------------------------------------------------------- remote status (updates + kill switch)
def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4])


def is_newer(latest, current=VERSION):
    try:
        return _vtuple(latest) > _vtuple(current)
    except ValueError:
        return False


def _status_cache():
    return os.path.join(home_dir(), "status.json")


def cached_status():
    try:
        with open(_status_cache(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def check_status(timeout=8):
    """Read status.json from the project's GitHub repo. Returns {} when offline (never raises).
    The only data that leaves the computer is the plain HTTPS request itself."""
    try:
        req = urllib.request.Request(STATUS_URL + f"?v={VERSION}", headers={"User-Agent": f"PyDM/{VERSION}", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read(20000).decode("utf-8"))
        if not isinstance(data, dict):
            return {}
        os.makedirs(home_dir(), exist_ok=True)
        with open(_status_cache(), "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data
    except Exception:  # noqa: BLE001
        return {}


def is_disabled(status):
    return status.get("enabled") is False

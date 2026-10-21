"""PyDM engine: multi-segment downloader with pause/resume, queue, schedule
and automatic folder sorting. Standard library only."""

import glob
import hashlib
import io
import json
import mimetypes
import os
import socket
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime

_SAVE_LOCK = threading.Lock()
HERE = os.path.dirname(os.path.abspath(__file__))
USER_LIB = os.path.join(os.path.expanduser("~"), ".pydm", "lib")   # updatable video engine
for _p in (os.path.join(HERE, "lib"), USER_LIB):                    # USER_LIB wins
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


import finder  # noqa: E402  (needs HERE on sys.path first)


def find_tool(name):
    exe = name + (".exe" if os.name == "nt" else "")
    p = os.path.join(HERE, "bin", exe)
    return p if os.path.exists(p) else shutil.which(name)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PyDM/1.0"
CHUNK = 64 * 1024
MIN_SEGMENT = 512 * 1024      # don't split files into pieces smaller than this
MAX_RETRIES = 6
TIMEOUT = 15

CATEGORIES = {
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".txt", ".epub", ".csv", ".html", ".htm"},
    "Design": {".psd", ".ai", ".fig", ".sketch", ".indd", ".eps", ".otf", ".ttf"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff"},
    "Compressed": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Programs": {".exe", ".msi", ".dmg", ".apk", ".deb", ".iso", ".pkg"},
}


# ----------------------------------------------------------------- helpers
def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def human_time(sec):
    if sec is None or sec < 0 or sec > 99 * 3600:
        return "--"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fix_mojibake(name):
    """HTTP headers are decoded as latin-1; recover UTF-8 names when possible."""
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def safe_name(name):
    name = urllib.parse.unquote(name).strip().strip(".")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name or "download"


def filename_from_headers(headers, url):
    cd = headers.get("Content-Disposition", "") or ""
    m = re.search(r"filename\*\s*=\s*[\w-]+'[^']*'([^;]+)", cd, re.I)
    if m:
        return safe_name(m.group(1))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    if m:
        return safe_name(_fix_mojibake(m.group(1)))
    base = os.path.basename(urllib.parse.urlparse(url).path)
    return safe_name(base) if base else "download"


MIME_EXT = {
    "video/mp4": ".mp4", "video/webm": ".webm", "video/x-matroska": ".mkv",
    "video/quicktime": ".mov", "video/mpeg": ".mpg", "video/3gpp": ".3gp",
    "audio/mp4": ".m4a", "audio/webm": ".webm", "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/x-rar-compressed": ".rar", "application/x-7z-compressed": ".7z",
    "application/gzip": ".gz", "application/x-msdownload": ".exe",
    "application/vnd.android.package-archive": ".apk",
    "text/html": ".html", "text/plain": ".txt", "text/csv": ".csv",
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "image/svg+xml": ".svg",
}


def add_extension(name, url, content_type):
    """If the name has no extension, derive one from the real file type
    (a 'mime=' URL parameter, else the Content-Type header)."""
    if os.path.splitext(name)[1]:
        return name
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    ctype = (q.get("mime", [""])[0] or content_type or "").split(";")[0].strip().lower()
    if not ctype or ctype in ("application/octet-stream", "binary/octet-stream"):
        return name
    ext = MIME_EXT.get(ctype) or mimetypes.guess_extension(ctype) or ""
    return name + ext


def category_for(name):
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "General"


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path) or os.path.exists(path + ".part"):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


def _request(url, extra=None):
    headers = {"User-Agent": UA, "Accept-Encoding": "identity"}
    headers.update(extra or {})
    # spaces / non-ASCII in a pasted link: percent-encode, keep existing %XX
    url = urllib.parse.quote(url, safe="%/:?&=#+,;@!$'()*~[]")
    return urllib.request.Request(url, headers=headers)


def cookie_header(url, cookies):
    """Cookie header value for `url`, from a list of browser cookie dicts."""
    u = urllib.parse.urlparse(url)
    host, path, https = (u.hostname or "").lower(), u.path or "/", u.scheme == "https"
    pairs = []
    for c in cookies or []:
        dom = (c.get("domain") or "").lower().lstrip(".")
        if not dom or not (host == dom or host.endswith("." + dom)):
            continue
        if c.get("secure") and not https:
            continue
        if not path.startswith(c.get("path") or "/"):
            continue
        pairs.append(f'{c.get("name", "")}={c.get("value", "")}')
    return "; ".join(pairs)


def probe(url, timeout=TIMEOUT, headers=None):
    """Ask the server for size, range support and file name."""
    req = _request(url, dict(headers or {}, Range="bytes=0-0"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        size, resumable = 0, False
        if r.status == 206:
            m = re.search(r"/(\d+)\s*$", r.headers.get("Content-Range", "") or "")
            if m:
                size, resumable = int(m.group(1)), True
        else:
            size = int(r.headers.get("Content-Length") or 0)
        name = filename_from_headers(r.headers, r.geturl())
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        has_cd = "filename" in (r.headers.get("Content-Disposition") or "").lower()
        name = add_extension(name, url, ctype)
        return {"size": size, "resumable": resumable, "filename": name,
                "is_page": ctype in ("text/html", "application/xhtml+xml") and not has_cd}


class RangeError(Exception):
    pass



# ------------------------------------------------------------- video pages
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def media_format(quality, have_ffmpeg):
    if quality == "audio":
        return "ba/b"
    cap = "" if quality == "best" else f"[height<=?{quality}]"
    return f"bv*{cap}+ba/b{cap}/b" if have_ffmpeg else f"b{cap}/b"


VIEWS_PREFIX = re.compile(r"^\s*[\d.,]+\s*[KMB]?\s+views?\s*[\u00b7\u2022|]?\s*"
                          r"([\d.,]+\s*[KMB]?\s+(reactions?|likes?))?\s*[|\-\u2013_:]*\s*", re.I)
SITE_SUFFIX = re.compile(r"\s*[|\-\u2013\u2014]\s*(Facebook|Instagram|TikTok|Twitter|X|YouTube|Vimeo)\s*$", re.I)


def clean_title(t):
    t = (t or "").strip()
    for _ in range(2):
        t = VIEWS_PREFIX.sub("", t, count=1)
        t = SITE_SUFFIX.sub("", t)
    return t.strip(" |-_") or "video"


def probe_vcodec(ff, path):
    """Video codec name of a file (e.g. 'h264', 'av1', 'hevc'), via ffmpeg."""
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    try:
        p = subprocess.run([ff, "-hide_banner", "-i", path], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30, **kw)
        m = re.search(r"Video:\s*([A-Za-z0-9_]+)", p.stderr.decode("utf-8", "replace"))
        return m.group(1).lower() if m else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class _Stopped(Exception):
    pass



def friendly_net_error(e):
    """Plain wording for the usual network failures; anything else unchanged."""
    reason = getattr(e, "reason", e)
    if isinstance(reason, (OSError, socket.timeout)) and not isinstance(e, urllib.error.HTTPError):
        return "Could not reach the site (check your connection)"
    return str(e) or e.__class__.__name__


def friendly_media_error(e):
    msg = ANSI.sub("", str(e)).strip()
    msg = re.sub(r"^(ERROR:\s*)+", "", msg)
    low = msg.lower()
    if "unsupported url" in low:
        return "No downloadable video found at this link"
    if "sign in" in low or "not a bot" in low or "login" in low:
        return "This video needs a signed-in account (private / age-restricted / bot check)"
    if "drm" in low:
        return "This video is DRM-protected, so it can't be downloaded"
    if "private video" in low:
        return "This video is private"
    if "video unavailable" in low or "not available" in low:
        return "This video is not available"
    if "unable to download webpage" in low or "urlopen error" in low:
        return "Could not reach the site (check your connection)"
    return msg[:160] or "Video extraction failed"


def _install_wheel(project, module):
    """Download the newest wheel of `project` from PyPI into ~/.pydm/lib."""
    with urllib.request.urlopen(f"https://pypi.org/pypi/{project}/json", timeout=30) as r:
        meta = json.load(r)
    wheel = next(u for u in meta["urls"] if u["packagetype"] == "bdist_wheel")
    with urllib.request.urlopen(wheel["url"], timeout=120) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
        raise IOError(f"{project}: download is corrupted")
    os.makedirs(USER_LIB, exist_ok=True)
    tmp = os.path.join(USER_LIB, f".{module}.new")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = [m for m in z.namelist() if m.startswith(module + "/")]
        z.extractall(tmp, members)
    dest = os.path.join(USER_LIB, module)
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(os.path.join(tmp, module), dest)
    shutil.rmtree(tmp, ignore_errors=True)
    return meta["info"]["version"]


def update_video_engine():
    """Fetch the newest yt-dlp (sites change often). Returns the version string."""
    ver = _install_wheel("yt-dlp", "yt_dlp")
    try:
        _install_wheel("yt-dlp-ejs", "yt_dlp_ejs")
    except Exception:  # noqa: BLE001 - optional component
        pass
    return ver


# ---------------------------------------------------------------- download
class Download:
    def __init__(self, url, connections=8, start_now=False, quality="best"):
        self.id = uuid.uuid4().hex[:8]
        self.quality = quality
        self.media = False       # True = video page handled by yt-dlp
        self.base = ""           # media output path without extension
        self.src = ""            # video URL found inside the page (for resume)
        self.kind = "auto"       # auto | page | media | file  (what the browser extension sent)
        self.page_url = ""       # page the video was found on (Referer)
        self.headers = {}        # Referer / User-Agent / Origin from the browser
        self.cookies = []        # browser cookies for the site (logged-in downloads)
        self.title_hint = ""     # suggested file name
        self.phase = "checking"  # checking (is it a plain file?) -> finding (look for a video in the page)
        self.fname_hint = ""     # exact file name the browser chose (extension-caught downloads)
        self._cookie_file = ""
        self._sniff_cookie = ""
        self.url = url
        self.connections = connections
        self.start_now = start_now
        self.name = safe_name(os.path.basename(urllib.parse.urlparse(url).path)) or url
        self.size = 0
        self.resumable = False
        self.category = ""
        self.save_dir = ""       # folder chosen in the Download File Info window ("" = <root>/<category>)
        self.cat_hint = ""       # category chosen there ("" = by file type)
        self.path = ""
        self.status = "queued"   # queued probing downloading paused completed error
        self.error = ""
        self.segments = []       # [start, end, next_byte_to_fetch]
        self.single_done = 0
        self.added = time.time()
        self.speed = 0.0
        self._stop = threading.Event()
        self._thread = None
        self._last_bytes = 0
        self._last_t = time.time()

    # -- persistence
    KEYS = ("id", "url", "connections", "name", "size", "resumable", "category",
            "path", "status", "error", "segments", "single_done", "added",
            "quality", "media", "base", "src", "kind", "page_url", "headers", "cookies",
            "title_hint", "fname_hint", "save_dir", "cat_hint")

    def to_dict(self):
        return {k: getattr(self, k) for k in self.KEYS}

    @classmethod
    def from_dict(cls, d):
        dl = cls(d["url"], d.get("connections", 8))
        for k in cls.KEYS:
            if k in d:
                setattr(dl, k, d[k])
        if dl.status in ("probing", "downloading", "converting"):
            dl.status = "paused"
        return dl

    # -- progress
    @property
    def downloaded(self):
        if self.status == "completed":
            return self.size or self.single_done
        if self.segments:
            return sum(max(0, min(s[2], s[1] + 1) - s[0]) for s in self.segments)
        return self.single_done

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def _hdrs(self, url, extra=None):
        h = dict(self.headers)
        ck = cookie_header(url, self.cookies)
        if ck:
            h["Cookie"] = ck
        h.update(extra or {})
        return h

    def _scrub(self):
        """Forget the browser session once it is no longer needed."""
        self.cookies = []
        if self._cookie_file and os.path.exists(self._cookie_file):
            try:
                os.remove(self._cookie_file)
            except OSError:
                pass

    def update_speed(self):
        now, done = time.time(), self.downloaded
        dt = now - self._last_t
        if dt >= 0.4:
            inst = max(0, done - self._last_bytes) / dt
            self.speed = inst if self.speed == 0 else 0.6 * self.speed + 0.4 * inst
            self._last_bytes, self._last_t = done, now
        if self.status != "downloading":
            self.speed = 0.0

    # -- control
    def start(self, root):
        if self.alive:
            return
        self._stop.clear()
        self.status = "probing"
        self.error = ""
        self._thread = threading.Thread(target=self._run, args=(root,), daemon=True)
        self._thread.start()

    def pause(self):
        self._stop.set()
        if not self.alive and self.status in ("queued", "probing", "downloading", "converting"):
            self.status = "paused"

    # -- worker
    def _run(self, root):
        self.phase = "checking"
        try:
            if self.kind == "media" and not self.media:
                self.media, self.src = True, self.src or self.url
            elif self.kind == "page" and not self.path:
                self.media = True               # the extension said: this is a page, use yt-dlp
            if self.media:
                self._run_media(root)
                return
            if not self.path:
                try:
                    info = probe(self.url, headers=self._hdrs(self.url))
                except urllib.error.HTTPError as e:
                    if e.code in (404, 410):
                        raise
                    info = None          # site blocks plain requests: let yt-dlp try
                if info is None or info["is_page"]:
                    self.media = True
                    self._run_media(root)
                    return
                self.size, self.resumable = info["size"], info["resumable"]
                fname = info["filename"]
                if self.fname_hint:
                    fname = safe_name(self.fname_hint) or fname
                elif self.title_hint and self.kind == "file":      # browser extension knows the page title
                    ext = os.path.splitext(fname)[1]
                    fname = (safe_name(self.title_hint)[:120].strip(" .") or "video") + ext
                self.category = self.cat_hint or category_for(fname)
                folder = self.save_dir or os.path.join(root, self.category)
                os.makedirs(folder, exist_ok=True)
                self.path = unique_path(folder, fname)
                self.name = os.path.basename(self.path)
                self._init_part()
            if self._stop.is_set():
                self.status = "paused"
                return
            self.status = "downloading"
            self._transfer()
            if self._stop.is_set():
                self.status = "paused"
            elif self.error:
                self.status = "error"
            else:
                self._finish()
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            self.error = friendly_net_error(e)
            self.status = "error"

    def _extract(self, yt_dlp, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and info.get("entries"):
                parent = info.get("title") or ""
                info = next((e for e in info["entries"] if e), None)
                if info and parent and (info.get("title") or "").startswith(parent):
                    info["title"] = parent        # drop the " (1)" yt-dlp appends
        if not info:
            raise ValueError("Unsupported URL")
        if info.get("extractor_key") in ("Generic", "HTML5MediaEmbed"):   # yt-dlp numbers page finds: "Title (1)"
            info["title"] = re.sub(r"\s*\(1\)\s*$", "", info.get("title") or "")
        return info

    def _try_candidates(self, yt_dlp, base_opts, cands, title, extra):
        for u in cands[:8]:
            if self._stop.is_set():
                raise _Stopped()
            o = dict(base_opts, **extra)
            try:
                info = self._extract(yt_dlp, o, u)
            except Exception:  # noqa: BLE001 - try the next candidate
                continue
            if title:
                info["title"] = title
            self.src = u
            return info, o
        return None

    def _media_extra(self):
        """yt-dlp options carrying the browser's Referer / User-Agent / cookies."""
        hdr = {"Referer": self.page_url or self.url, "User-Agent": finder.BROWSER_UA}
        hdr.update(self.headers)
        extra = {"http_headers": hdr}
        if self.cookies:
            d = os.path.join(os.path.expanduser("~"), ".pydm", "cookies")
            os.makedirs(d, exist_ok=True)
            self._cookie_file = os.path.join(d, f"{self.id}.txt")
            finder.write_cookiefile(self.cookies, self._cookie_file)
            extra["cookiefile"] = self._cookie_file
        return extra

    def _find_video(self, yt_dlp, base_opts):
        """yt-dlp on the link -> media links in the page source -> hidden browser."""
        not_found = "No downloadable video found at this link"
        mine = self._media_extra()
        hdr = mine["http_headers"]
        if self.src:                                   # a media URL we already know
            try:
                o = dict(base_opts, **mine)
                return self._extract(yt_dlp, o, self.src), o
            except Exception:  # noqa: BLE001
                if self.kind == "media":
                    raise
                self.src = ""
        try:                                           # 1) sites yt-dlp knows
            o = dict(base_opts, **mine) if (self.headers or self.cookies) else base_opts
            return self._extract(yt_dlp, o, self.url), o
        except Exception as e:  # noqa: BLE001
            if friendly_media_error(e) != not_found:
                raise
        if self._stop.is_set():
            raise _Stopped()
        title, cands = "", []
        try:                                           # 2) links inside the page source
            text, final = finder.fetch_html(self.url)
            title, cands = finder.page_title(text), finder.scan_html(text, final)
        except Exception:  # noqa: BLE001
            pass
        got = self._try_candidates(yt_dlp, base_opts, cands, title, mine)
        if got:
            return got
        if self._stop.is_set():
            raise _Stopped()
        res = finder.sniff(self.url, stop=self._stop)  # 3) hidden browser watches the network
        if res and res["candidates"]:
            extra = dict(mine, http_headers=dict(hdr, **{"User-Agent": res["ua"]}))
            if res["cookies"] and not self.cookies:
                self._sniff_cookie = os.path.join(tempfile.gettempdir(), f"pydm_ck_{self.id}.txt")
                finder.write_cookiefile(res["cookies"], self._sniff_cookie)
                extra["cookiefile"] = self._sniff_cookie
            got = self._try_candidates(yt_dlp, base_opts, res["candidates"],
                                       res["title"] or title, extra)
            if got:
                return got
        raise ValueError(not_found)

    def _ensure_playable(self, ff):
        """AV1 / HEVC don't play in Windows Media Player without paid extensions:
        convert those to H.264."""
        codec = probe_vcodec(ff, self.path)
        if codec not in ("av1", "hevc", "h265"):
            return
        self.status = "converting"
        out = os.path.splitext(self.path)[0] + ".h264tmp.mp4"
        cmd = [ff, "-y", "-loglevel", "error", "-i", self.path, "-map", "0:v:0", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out]
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **kw)
        while p.poll() is None:
            if self._stop.is_set():
                p.kill()
                p.wait()
                break
            time.sleep(0.3)
        if p.returncode == 0 and os.path.exists(out):
            final = os.path.splitext(self.path)[0] + ".mp4"
            if final != self.path:
                os.remove(self.path)
            os.replace(out, final)
            self.path = final
        elif os.path.exists(out):
            os.remove(out)                  # stopped or failed: keep the original file

    def _run_media(self, root):
        """The link is a web page: find its video, then download it."""
        try:
            import yt_dlp
        except ImportError:
            self.error, self.status = "Video engine (yt-dlp) is missing - reinstall PyDM", "error"
            return
        self.status = "probing"
        self.phase = "finding"
        host = urllib.parse.urlparse(self.url).netloc or self.url
        if not self.base:
            self.name = f"{host} - looking for video..."
        ff, deno = find_tool("ffmpeg"), find_tool("deno")
        opts = {
            "quiet": True, "no_warnings": True, "noprogress": True,
            "noplaylist": True, "playlist_items": "1",
            "format": media_format(self.quality, bool(ff)),
            # prefer H.264/AAC so the file plays everywhere, then the highest resolution
            "format_sort": ["vcodec:h264", "res", "acodec:aac", "ext:mp4:m4a"],
            "merge_output_format": "mp4",
            "socket_timeout": 20, "retries": 8, "fragment_retries": 8,
            "concurrent_fragment_downloads": 4, "continuedl": True,
            "color": "never",
        }
        if ff:
            opts["ffmpeg_location"] = os.path.dirname(ff)
        if deno:
            opts["js_runtimes"] = {"deno": {"path": deno}}
        try:
            info, opts = self._find_video(yt_dlp, opts)
            if self._stop.is_set():
                raise _Stopped()
            if self.title_hint:
                info["title"] = self.title_hint
            if not self.base:
                title = safe_name(clean_title(info.get("title")))[:120]
                fmts = info.get("requested_formats") or []
                ext = "mp4" if len(fmts) > 1 else (info.get("ext") or "mp4")
                if self.quality == "audio" and ext in ("mp4", "webm"):
                    ext = "m4a" if ext == "mp4" else ext
                self.category = self.cat_hint or category_for("x." + ext)
                if self.category == "General":
                    self.category = "Videos"
                folder = self.save_dir or os.path.join(root, self.category)
                os.makedirs(folder, exist_ok=True)
                base, n = os.path.join(folder, title), 1
                while glob.glob(glob.escape(base) + ".*"):
                    base = os.path.join(folder, f"{title} ({n})")
                    n += 1
                self.base = base
                self.name = os.path.basename(base) + "." + ext
                self.path = base + "." + ext
            fmts = info.get("requested_formats") or [info]
            est = sum((f.get("filesize") or f.get("filesize_approx") or 0) for f in fmts)
            self.size = est or self.size
            parts, totals = {}, {}

            def hook(d):
                if self._stop.is_set():
                    raise _Stopped()
                fn = d.get("filename")
                parts[fn] = d.get("downloaded_bytes") or d.get("total_bytes") or 0
                tot = d.get("total_bytes") or d.get("total_bytes_estimate")
                if tot:
                    totals[fn] = tot
                self.single_done = sum(parts.values())
                self.size = max(est, sum(totals.values()), self.single_done)

            opts2 = dict(opts, outtmpl=self.base + ".%(ext)s", progress_hooks=[hook])
            self.status = "downloading"
            with yt_dlp.YoutubeDL(opts2) as ydl:
                res = ydl.process_ie_result(info, download=True)
            done = [d["filepath"] for d in (res.get("requested_downloads") or [])
                    if d.get("filepath") and os.path.exists(d["filepath"])]
            if not done:
                done = [p for p in glob.glob(glob.escape(self.base) + ".*")
                        if not p.endswith((".part", ".ytdl"))]
            if not done:
                raise IOError("Download finished but the file was not found")
            self.path = done[0]
            if ff and self.quality != "audio":
                self._ensure_playable(ff)
            self.name = os.path.basename(self.path)
            self.size = os.path.getsize(self.path)
            self.single_done = self.size
            self.status, self.speed = "completed", 0.0
            self._scrub()
        except _Stopped:
            self.status = "paused"
        except Exception as e:  # noqa: BLE001
            if self._stop.is_set():
                self.status = "paused"
            else:
                self.error, self.status = friendly_media_error(e), "error"
                if not self.base:
                    self.name = host
        finally:
            if self._sniff_cookie and os.path.exists(self._sniff_cookie):
                try:
                    os.remove(self._sniff_cookie)
                except OSError:
                    pass

    def _init_part(self):
        part = self.path + ".part"
        self.single_done = 0
        self.segments = []
        if self.resumable and self.size > 0:
            n = max(1, min(self.connections, self.size // MIN_SEGMENT))
            step = self.size // n
            for i in range(n):
                s = i * step
                e = self.size - 1 if i == n - 1 else (i + 1) * step - 1
                self.segments.append([s, e, s])
            with open(part, "wb") as f:
                f.truncate(self.size)
        else:
            open(part, "wb").close()

    def _transfer(self):
        part = self.path + ".part"
        if not os.path.exists(part):
            self._init_part()        # part file was deleted: start over
        if self.segments:
            threads = []
            for seg in self.segments:
                if seg[2] <= seg[1]:
                    t = threading.Thread(target=self._segment_worker,
                                         args=(seg, part), daemon=True)
                    t.start()
                    threads.append(t)
            for t in threads:
                t.join()
            if (not self._stop.is_set() and not self.error
                    and any(s[2] <= s[1] for s in self.segments)):
                self.error = "Download incomplete"
        else:
            self._single_stream(part)

    def _segment_worker(self, seg, part):
        retries = 0
        with open(part, "r+b", buffering=0) as f:
            while seg[2] <= seg[1] and not self._stop.is_set() and not self.error:
                before = seg[2]
                try:
                    req = _request(self.url, self._hdrs(self.url, {"Range": f"bytes={seg[2]}-{seg[1]}"}))
                    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                        if r.status != 206:
                            raise RangeError("Server did not honor the Range request")
                        while not self._stop.is_set():
                            data = r.read(CHUNK)
                            if not data:
                                break
                            data = data[: seg[1] - seg[2] + 1]
                            f.seek(seg[2])
                            f.write(data)
                            seg[2] += len(data)
                            if seg[2] > seg[1]:
                                break
                except RangeError as e:
                    self.error = str(e)
                    return
                except urllib.error.HTTPError as e:
                    if 400 <= e.code < 500 and e.code not in (408, 429):
                        self.error = f"HTTP {e.code} {e.reason}"
                        return
                    retries += 1
                except Exception:  # noqa: BLE001 - network hiccup, retry
                    retries += 1
                else:
                    retries = 0 if seg[2] > before else retries + 1
                if retries > MAX_RETRIES:
                    self.error = "Connection failed (too many retries)"
                    return
                if retries and not self._stop.is_set():
                    time.sleep(min(2 ** retries, 8))

    def _single_stream(self, part):
        """Server can't resume: one connection, restart from zero if interrupted."""
        for attempt in range(3):
            self.single_done = 0
            try:
                with urllib.request.urlopen(_request(self.url, self._hdrs(self.url)), timeout=TIMEOUT) as r, \
                        open(part, "wb") as f:
                    while not self._stop.is_set():
                        data = r.read(CHUNK)
                        if not data:
                            break
                        f.write(data)
                        self.single_done += len(data)
                    else:
                        return       # paused
                if self.size and self.single_done != self.size:
                    raise IOError("Download incomplete")
                self.size = self.size or self.single_done
                return
            except urllib.error.HTTPError as e:
                self.error = f"HTTP {e.code} {e.reason}"
                return
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    self.error = friendly_net_error(e)
                    return
                time.sleep(2)

    def _finish(self):
        os.replace(self.path + ".part", self.path)
        self.size = self.size or self.single_done
        self.status = "completed"
        self.speed = 0.0
        self._scrub()


# ----------------------------------------------------------------- manager
class Manager:
    def __init__(self, home=None):
        self.home = home or os.path.join(os.path.expanduser("~"), ".pydm")
        os.makedirs(self.home, exist_ok=True)
        self.settings = {
            "root": os.path.join(os.path.expanduser("~"), "Downloads", "PyDM"),
            "max_concurrent": 3,
            "connections": 8,
            "quality": "best",
            "language": "auto",
            "theme": "auto",
            "autostart": False,
        }
        self.items = []
        self.lock = threading.RLock()
        self.queue_active = False
        self.start_at = None      # datetime when the queue should start
        self._load()
        self._quit = threading.Event()
        self._loop_thread = threading.Thread(target=self._loop, daemon=True)
        self._loop_thread.start()

    # -- persistence
    @property
    def _state_file(self):
        return os.path.join(self.home, "state.json")

    def _load(self):
        try:
            with open(self._state_file, encoding="utf-8") as f:
                data = json.load(f)
            self.settings.update(data.get("settings", {}))
            self.items = [Download.from_dict(d) for d in data.get("items", [])]
        except (OSError, ValueError, KeyError):
            pass

    def save(self):
        with self.lock:
            data = {"settings": self.settings,
                    "items": [i.to_dict() for i in self.items]}
        with _SAVE_LOCK:                      # two threads saving at once used to fight over the same .tmp file
            tmp = self._state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._state_file)

    # -- public API
    def add_urls(self, urls, connections=None, start_now=False, quality="best"):
        added = []
        with self.lock:
            for url in urls:
                url = url.strip()
                if not url.lower().startswith(("http://", "https://")):
                    continue
                dl = Download(url, connections or self.settings["connections"], start_now, quality)
                self.items.append(dl)
                added.append(dl)
        self.save()
        return added

    def add_item(self, spec):
        """Add one download described by the browser extension or the UI."""
        url = (spec.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return None
        dl = Download(url, int(spec.get("connections") or self.settings["connections"]),
                      bool(spec.get("start_now", True)),
                      spec.get("quality") or self.settings.get("quality", "best"))
        kind = spec.get("kind") or "auto"
        dl.kind = kind if kind in ("auto", "page", "media", "file") else "auto"
        dl.page_url = (spec.get("page_url") or "")[:2000]
        for key, field in (("referer", "Referer"), ("user_agent", "User-Agent"), ("origin", "Origin")):
            if spec.get(key):
                dl.headers[field] = str(spec[key])[:1000]
        dl.cookies = [{k: c.get(k) for k in ("name", "value", "domain", "path", "secure", "httpOnly", "expires")}
                      for c in (spec.get("cookies") or [])[:300] if isinstance(c, dict) and c.get("name")]
        dl.title_hint = re.sub(r"\s+", " ", str(spec.get("title") or "")).strip()[:200]
        dl.fname_hint = os.path.basename(str(spec.get("filename") or "").replace("\\", "/"))[:200]
        if spec.get("category") in CATEGORIES or spec.get("category") == "General":
            dl.cat_hint = spec["category"]
        sd = str(spec.get("save_dir") or "").strip()
        if sd and os.path.isabs(sd):
            dl.save_dir = os.path.normpath(sd)
        if dl.kind == "media":
            dl.media, dl.src = True, url
        if dl.fname_hint:
            dl.name = dl.fname_hint
        elif dl.title_hint:
            dl.name = dl.title_hint
        with self.lock:
            self.items.append(dl)
        self.save()
        return dl

    def clear_finished(self):
        with self.lock:
            gone = [i for i in self.items if i.status == "completed"]
            self.items = [i for i in self.items if i.status != "completed"]
        return len(gone)

    def active_count(self):
        with self.lock:
            return sum(1 for i in self.items
                       if i.status in ("queued", "probing", "downloading", "converting"))

    def get(self, dl_id):
        with self.lock:
            return next((i for i in self.items if i.id == dl_id), None)

    def pause(self, dl_id):
        dl = self.get(dl_id)
        if dl and dl.status in ("queued", "probing", "downloading", "converting"):
            dl.start_now = False
            dl.pause()

    def resume(self, dl_id):
        dl = self.get(dl_id)
        if dl and dl.status in ("paused", "error"):
            dl.status, dl.error, dl.start_now = "queued", "", True

    def remove(self, dl_id, delete_files=False):
        dl = self.get(dl_id)
        if not dl:
            return
        with self.lock:
            self.items.remove(dl)
        dl.pause()

        def cleanup():
            if dl._thread:
                dl._thread.join(timeout=TIMEOUT + 5)
            dl._scrub()
            doomed = []
            if dl.path:
                doomed += [dl.path + ".part", dl.path if delete_files else None]
            if dl.base:     # yt-dlp leaves .part / .ytdl / .fNNN pieces next to the file
                for p in glob.glob(glob.escape(dl.base) + ".*"):
                    if p.endswith((".part", ".ytdl")) or re.search(r"\.f[\w-]+\.\w+$", p):
                        doomed.append(p)
                    elif delete_files:
                        doomed.append(p)
            for p in doomed:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            self.save()
        threading.Thread(target=cleanup, daemon=True).start()

    def set_queue(self, active):
        self.queue_active = bool(active)
        if active:
            self.start_at = None

    def schedule(self, when):
        """Run the queue at `when` (datetime), or cancel with None."""
        self.start_at = when
        if when:
            self.queue_active = False

    def snapshot(self):
        rows = []
        with self.lock:
            for i in self.items:
                left = i.size - i.downloaded
                eta = left / i.speed if i.speed > 1 and i.size else None
                rows.append({"id": i.id, "name": i.name, "size": i.size,
                             "done": i.downloaded, "speed": i.speed, "eta": eta,
                             "status": i.status, "error": i.error,
                             "category": i.category, "path": i.path, "url": i.url,
                             "host": urllib.parse.urlparse(i.page_url or i.url).netloc,
                             "quality": i.quality, "media": i.media, "added": i.added,
                             "phase": i.phase, "resumable": i.resumable,
                             "segments": [list(x) for x in i.segments] if i.status == "downloading" else []})
        return rows

    def shutdown(self):
        with self.lock:
            items = list(self.items)
        for i in items:
            if i.status in ("queued", "probing", "downloading", "converting"):
                i.pause()
        deadline = time.time() + 4
        for i in items:
            if i._thread:
                i._thread.join(timeout=max(0.1, deadline - time.time()))
        self._quit.set()
        self.save()

    # -- background loop
    def _loop(self):
        last_save = time.time()
        while not self._quit.is_set():
            try:
                self._tick()
                if time.time() - last_save > 3:
                    self.save()
                    last_save = time.time()
            except Exception:  # noqa: BLE001 - never let the loop die
                pass
            time.sleep(0.4)

    def _tick(self):
        if self.start_at and datetime.now() >= self.start_at:
            self.queue_active, self.start_at = True, None
        with self.lock:
            items = list(self.items)
        for i in items:
            i.update_speed()
        running = sum(1 for i in items if i.status in ("probing", "downloading", "converting"))
        for i in items:
            if i.status != "queued":
                continue
            if i.start_now:
                i.start(self.settings["root"])
                i.start_now = False
                running += 1
            elif self.queue_active and running < self.settings["max_concurrent"]:
                i.start(self.settings["root"])
                running += 1
        if self.queue_active and not any(
                i.status in ("queued", "probing", "downloading", "converting") for i in items):
            self.queue_active = False     # queue finished

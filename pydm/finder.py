"""Find the video behind a web page.

Layer A - scan the page's HTML for media links (<video>, <source>, og:video,
          .mp4/.m3u8/.mpd URLs hidden in scripts / JSON).
Layer B - open the page in a hidden Chrome and watch the network, exactly
          like a download-manager browser extension does (for players that
          load the video with JavaScript).
Standard library only (a tiny WebSocket client is included).
"""

import base64
import html as htmllib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v", ".mkv")
MANIFEST_EXT = (".m3u8", ".mpd")
MANIFEST_MIME = ("application/vnd.apple.mpegurl", "application/x-mpegurl",
                 "audio/mpegurl", "audio/x-mpegurl", "application/dash+xml")
JUNK_HINTS = ("thumbnail", "thumb_", "poster", "sprite", "preview", "favicon", "/ads/", "adserver")


# ------------------------------------------------------------- static scan
def fetch_html(url, timeout=15, limit=3_000_000):
    req = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(limit)
        final = r.geturl()
        charset = r.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace"), final
    except LookupError:
        return raw.decode("utf-8", errors="replace"), final


def page_title(text):
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', text, re.I) \
        or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title', text, re.I) \
        or re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return htmllib.unescape(m.group(1)).strip() if m else ""


def _kind(u):
    p = urllib.parse.urlparse(u).path.lower()
    if p.endswith(MANIFEST_EXT):
        return "manifest"
    if p.endswith(VIDEO_EXT):
        return "file"
    return ""


def scan_html(text, base_url):
    """Return media URLs found in the page source, manifests first."""
    t = (text.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&")
         .replace("&amp;", "&").replace("\\u003d", "="))
    found = []
    for m in re.finditer(r"https?://[^\s\"'<>\\)\]]+?\.(?:m3u8|mpd|mp4|webm|mov|m4v)"
                         r"(?:\?[^\s\"'<>\\)\]]*)?", t, re.I):
        found.append(m.group(0))
    for m in re.finditer(r"<(?:video|source)\b[^>]*?\ssrc\s*=\s*[\"']([^\"']+)[\"']", t, re.I):
        found.append(urllib.parse.urljoin(base_url, m.group(1)))
    for m in re.finditer(r"<meta[^>]+(?:property|name)=[\"']og:video(?::secure_url|:url)?[\"']"
                         r"[^>]+content=[\"']([^\"']+)", t, re.I):
        found.append(urllib.parse.urljoin(base_url, m.group(1)))
    out, seen = [], set()
    for u in found:
        u = u.strip()
        if not u.lower().startswith(("http://", "https://")) or u in seen:
            continue
        if any(h in u.lower() for h in JUNK_HINTS):
            continue
        seen.add(u)
        out.append(u)
    out.sort(key=lambda u: 0 if _kind(u) == "manifest" else 1)
    return out


# ------------------------------------------------------------ mini WebSocket
class _WS:
    def __init__(self, url, timeout=30):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                           f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake failed")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise ConnectionError("WebSocket upgrade refused")
        self.buf = rest
        self._frag = b""

    def send(self, text):
        data = text.encode()
        n = len(data)
        head = bytes([0x81])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _frame(self):
        b = self.buf
        if len(b) < 2:
            return None
        op, ln, off = b[0] & 0x0F, b[1] & 0x7F, 2
        fin = bool(b[0] & 0x80)
        if ln == 126:
            if len(b) < 4:
                return None
            ln, off = struct.unpack(">H", b[2:4])[0], 4
        elif ln == 127:
            if len(b) < 10:
                return None
            ln, off = struct.unpack(">Q", b[2:10])[0], 10
        if len(b) < off + ln:
            return None
        payload = b[off:off + ln]
        self.buf = b[off + ln:]
        return fin, op, payload

    def recv(self, timeout=0.5):
        """Next text message, or None if nothing arrived within `timeout`."""
        end = time.time() + timeout
        while True:
            fr = self._frame()
            if fr:
                fin, op, payload = fr
                if op == 0x8:
                    raise ConnectionError("browser closed the connection")
                if op == 0x9:
                    self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                    continue
                if op in (0x1, 0x0):
                    self._frag += payload
                    if fin:
                        msg, self._frag = self._frag, b""
                        return msg.decode("utf-8", "replace")
                continue
            left = end - time.time()
            if left <= 0:
                return None
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("browser closed the connection")
            self.buf += chunk

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class _CDP:
    def __init__(self, ws):
        self.ws, self.n, self.on_event = ws, 0, None

    def _dispatch(self, raw):
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def call(self, method, params=None, timeout=10):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            raw = self.ws.recv(0.3)
            if raw is None:
                continue
            m = self._dispatch(raw)
            if m.get("id") == mid:
                return m.get("result") or {}
            if "method" in m and self.on_event:
                self.on_event(m)
        return {}

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            raw = self.ws.recv(min(0.25, max(0.01, end - time.time())))
            if raw:
                m = self._dispatch(raw)
                if "method" in m and self.on_event:
                    self.on_event(m)


# ---------------------------------------------------------------- browser
def find_browser():
    env = os.environ.get("PYDM_BROWSER")
    if env and os.path.exists(env):
        return env
    cands = []
    if os.name == "nt":
        for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
    else:
        for n in ("google-chrome", "chromium", "chromium-browser", "brave-browser"):
            p = shutil.which(n)
            if p:
                cands.append(p)
    return next((c for c in cands if os.path.exists(c)), None)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _classify(url, mime, headers, status):
    if url.startswith(("data:", "blob:")) or (status and status >= 400):
        return None
    low = url.lower()
    if any(h in low for h in JUNK_HINTS):
        return None
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith(MANIFEST_EXT) or mime in MANIFEST_MIME:
        return "manifest", 0
    if mime.startswith("video/") or (path.endswith(VIDEO_EXT) and mime != "text/html"):
        if path.endswith((".ts", ".m4s", ".cmfv")) or mime == "video/mp2t":
            return None
        size = 0
        cr = headers.get("content-range", "")
        m = re.search(r"/(\d+)\s*$", cr)
        if m:
            size = int(m.group(1))
        elif headers.get("content-length", "").isdigit():
            size = int(headers["content-length"])
        if 0 < size < 150_000:
            return None          # tiny fragment / ad bumper
        return "file", size
    return None


def sniff(url, stop=None, timeout=30):
    """Open `url` in a hidden browser and return what it tried to play.

    -> {"title": str, "candidates": [url, ...], "cookies": [...], "ua": str}
       or None when no usable browser exists."""
    exe = find_browser()
    if not exe:
        return None
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="pydm_br_")
    args = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--mute-audio", "--autoplay-policy=no-user-gesture-required",
            "--remote-allow-origins=*", "--window-size=1280,800",
            f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.insert(1, "--no-sandbox")
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kw)
    ws = None
    try:
        page_ws, end = None, time.time() + 15
        while time.time() < end and not page_ws:
            if proc.poll() is not None:
                return None
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    for t in json.load(r):
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                            page_ws = t["webSocketDebuggerUrl"]
                            break
            except (OSError, ValueError):
                time.sleep(0.3)
        if not page_ws:
            return None
        ws = _WS(page_ws)
        cdp = _CDP(ws)
        found = {}          # url -> [kind, size]
        order = []

        def on_event(m):
            if m.get("method") != "Network.responseReceived":
                return
            r = (m.get("params") or {}).get("response") or {}
            u = r.get("url", "")
            hdr = {k.lower(): str(v) for k, v in (r.get("headers") or {}).items()}
            c = _classify(u, (r.get("mimeType") or "").lower(), hdr, r.get("status"))
            if c:
                if u not in found:
                    found[u] = list(c)
                    order.append(u)
                else:
                    found[u][1] = max(found[u][1], c[1])
        cdp.on_event = on_event
        cdp.call("Network.enable")
        cdp.call("Page.enable")
        cdp.call("Network.setUserAgentOverride", {"userAgent": BROWSER_UA})
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        cdp.call("Page.navigate", {"url": url})

        play_js = ("(()=>{document.querySelectorAll('video').forEach(v=>{v.muted=true;"
                   "try{v.play()}catch(e){}});const b=document.querySelector("
                   "'[class*=play i],[aria-label*=play i],button[title*=play i]');"
                   "if(b){try{b.click()}catch(e){}}})()")
        t0, did = time.time(), set()
        while time.time() - t0 < timeout:
            if stop is not None and stop.is_set():
                break
            cdp.pump(0.4)
            el = time.time() - t0
            if el > 2 and "p1" not in did:
                did.add("p1")
                cdp.call("Runtime.evaluate", {"expression": play_js})
            if el > 4 and "click" not in did:
                did.add("click")
                for typ in ("mousePressed", "mouseReleased"):
                    cdp.call("Input.dispatchMouseEvent", {"type": typ, "x": 640, "y": 400,
                                                          "button": "left", "clickCount": 1})
            if el > 7 and "p2" not in did:
                did.add("p2")
                cdp.call("Runtime.evaluate", {"expression": play_js})
            kinds = [found[u][0] for u in order]
            if "manifest" in kinds and el > 4:
                cdp.pump(1.0)
                break
            if "file" in kinds and el > 5:
                cdp.pump(1.0)
                break
        title = ""
        r = cdp.call("Runtime.evaluate", {
            "expression": "((document.querySelector('meta[property=\"og:title\"]')||{}).content)"
                          "||document.title||''", "returnByValue": True})
        title = ((r.get("result") or {}).get("value") or "").strip()
        cookies = cdp.call("Network.getAllCookies").get("cookies", [])
        manifests = [u for u in order if found[u][0] == "manifest"]
        files = sorted((u for u in order if found[u][0] == "file"),
                       key=lambda u: -found[u][1])
        return {"title": title, "candidates": manifests + files,
                "cookies": cookies, "ua": BROWSER_UA}
    finally:
        if ws:
            ws.close()
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(profile, ignore_errors=True)


def write_cookiefile(cookies, path):
    """Netscape cookie file for yt-dlp from CDP cookie dicts."""
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        dom = c.get("domain", "")
        exp = int(c.get("expires") or 0)
        lines.append("\t".join([
            ("#HttpOnly_" if c.get("httpOnly") else "") + dom,
            "TRUE" if dom.startswith(".") else "FALSE", c.get("path", "/"),
            "TRUE" if c.get("secure") else "FALSE", str(exp if exp > 0 else 0),
            c.get("name", ""), c.get("value", "")]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

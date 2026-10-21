"""PyDM local server: serves the web UI and the JSON API that the UI and the
browser extension talk to. Listens on 127.0.0.1 only and requires a secret
token (kept in ~/.pydm/token) for every API call except /api/ping."""

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import engine

PORT_BASE = int(os.environ.get("PYDM_PORT", "47321"))
PORT_TRIES = 10
UI_DIR = os.path.join(engine.HERE, "ui")
MAX_BODY = 4 * 1024 * 1024
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon",
        ".json": "application/json; charset=utf-8"}
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


from shell import (VERSION, EXT_DIR, home_dir, load_token, ping, find_running, call,  # noqa: E402,F401
                   open_path, reveal, ytdlp_version)


def pick_folder(initial):
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    code = ("import tkinter as tk\nfrom tkinter import filedialog\nr=tk.Tk();r.withdraw()\n"
            "r.attributes('-topmost',True)\n"
            f"print(filedialog.askdirectory(initialdir={initial!r}, mustexist=False) or '')")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([exe, "-c", code], capture_output=True, timeout=600,
                       creationflags=NO_WINDOW, env=env)
    return p.stdout.decode("utf-8", "replace").strip()


def set_autostart(enabled):
    if os.name != "nt":
        return False
    import winreg
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
    with key:
        if enabled:
            exe = sys.executable
            if exe.lower().endswith("python.exe"):
                exe = exe[:-len("python.exe")] + "pythonw.exe"
            app = os.path.join(engine.HERE, "app.py")
            winreg.SetValueEx(key, "PyDM", 0, winreg.REG_SZ, f'"{exe}" "{app}" --background')
        else:
            try:
                winreg.DeleteValue(key, "PyDM")
            except FileNotFoundError:
                pass
    return enabled


# ---------------------------------------------------------------- server
class PyDMServer:
    def __init__(self, manager, token, on_show=None, on_quit=None):
        self.mgr, self.token = manager, token
        self.on_show, self.on_quit = on_show or (lambda: None), on_quit or (lambda: None)
        self.httpd, self.port = None, None
        self.show_seq = 0                 # bumped on every "open the window" request

    # -- lifecycle
    def start(self):
        outer = self
        for p in range(PORT_BASE, PORT_BASE + PORT_TRIES):
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", p), _make_handler(outer))
                self.port = p
                break
            except OSError:
                continue
        if not self.httpd:
            raise OSError("No free local port for PyDM")
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.write_extension_config()
        return self.port

    def stop(self):
        if self.httpd:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    def write_extension_config(self):
        try:
            os.makedirs(EXT_DIR, exist_ok=True)
            with open(os.path.join(EXT_DIR, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"port": self.port, "token": self.token, "version": VERSION}, f)
        except OSError:
            pass

    # -- data
    def state(self):
        m = self.mgr
        rows = m.snapshot()
        return {
            "version": VERSION, "items": rows,
            "speed": sum(r["speed"] for r in rows),
            "queue": {"active": m.queue_active,
                      "start_at": m.start_at.isoformat() if m.start_at else None},
            "settings": m.settings,
            "engine": ytdlp_version(),
            "extension_dir": EXT_DIR, "windows": os.name == "nt", "show_seq": self.show_seq, "pid": os.getpid(),
        }

    # -- API
    def handle(self, path, body):
        m = self.mgr
        if path == "/api/state":
            return self.state()
        if path == "/api/add":
            specs = body.get("items") or [body]
            if body.get("urls"):
                specs = [dict(body, url=u) for u in body["urls"]]
            added = []
            for spec in specs:
                for url in str(spec.get("url") or "").split():       # allow pasted multi-line text
                    dl = m.add_item(dict(spec, url=url))
                    if dl:
                        added.append(dl.id)
            return {"added": added}
        if path == "/api/item":
            dl = m.get(body.get("id", ""))
            act = body.get("action")
            if not dl:
                return {"ok": False}
            if act == "pause":
                m.pause(dl.id)
            elif act in ("resume", "retry"):
                m.resume(dl.id)
            elif act == "remove":
                m.remove(dl.id, bool(body.get("delete_files")))
            elif act == "open" and dl.status == "completed" and os.path.exists(dl.path):
                open_path(dl.path)
            elif act == "folder" and dl.path:
                reveal(dl.path)
            return {"ok": True}
        if path == "/api/queue":
            m.set_queue(body.get("action") == "start")
            return {"ok": True}
        if path == "/api/schedule":
            t = body.get("time")
            if not t:
                m.schedule(None)
            else:
                hh, mm = (int(x) for x in str(t).split(":"))
                when = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
                if when <= datetime.now():
                    when += timedelta(days=1)
                m.schedule(when)
            return {"ok": True}
        if path == "/api/settings":
            s = m.settings
            if "root" in body and str(body["root"]).strip():
                s["root"] = str(body["root"]).strip()
            for key, lo, hi in (("max_concurrent", 1, 10), ("connections", 1, 32)):
                if key in body:
                    s[key] = max(lo, min(hi, int(body[key])))
            if body.get("quality") in ("best", "1080", "720", "480", "360", "audio"):
                s["quality"] = body["quality"]
            if body.get("language") in ("auto", "ar", "en"):
                s["language"] = body["language"]
            if body.get("theme") in ("auto", "light", "dark"):
                s["theme"] = body["theme"]
            for flag in ("notify", "tray_hint"):
                if flag in body:
                    s[flag] = bool(body[flag])
            if "autostart" in body:
                s["autostart"] = bool(body["autostart"])
                try:
                    set_autostart(s["autostart"])
                except OSError:
                    pass
            m.save()
            return {"ok": True, "settings": s}
        if path == "/api/clear-finished":
            return {"removed": m.clear_finished()}
        if path == "/api/open-url":
            u = str(body.get("url", ""))
            if u.lower().startswith(("http://", "https://")):
                webbrowser.open_new_tab(u)
            return {"ok": True}
        if path == "/api/open-folder":
            os.makedirs(m.settings["root"], exist_ok=True)
            open_path(m.settings["root"])
            return {"ok": True}
        if path == "/api/open-extension":
            os.makedirs(EXT_DIR, exist_ok=True)
            open_path(EXT_DIR)
            return {"ok": True}
        if path == "/api/browse":
            return {"path": pick_folder(m.settings["root"])}
        if path == "/api/update-engine":
            try:
                return {"ok": True, "version": engine.update_video_engine()}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)[:200]}
        if path == "/api/show":
            self.show_seq += 1
            self.on_show()
            return {"ok": True}
        if path == "/api/quit":
            threading.Thread(target=self.on_quit, daemon=True).start()
            return {"ok": True}
        return None


def _make_handler(srv):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):          # pythonw has no stderr
            pass

        # -- plumbing
        def _host_ok(self):
            return self.headers.get("Host", "").rsplit(":", 1)[0].lower() in ("127.0.0.1", "localhost")

        def _send(self, code, ctype, data, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, "application/json; charset=utf-8",
                       json.dumps(obj, ensure_ascii=False).encode(), {"Cache-Control": "no-store"})

        def _authed(self):
            return secrets.compare_digest(self.headers.get("X-PyDM-Token", ""), srv.token)

        # -- verbs
        def do_OPTIONS(self):                # no CORS: web pages cannot call the API
            self._send(204, "text/plain", b"")

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, "text/plain", b"forbidden")
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/ping":
                return self._json({"app": "pydm", "version": VERSION})
            if path.startswith("/api/"):
                if not self._authed():
                    return self._json({"error": "unauthorized"}, 401)
                out = srv.handle(path, {}) if path == "/api/state" else None
                return self._json(out if out is not None else {"error": "not found"},
                                  200 if out is not None else 404)
            if path in ("/", "/index.html"):
                try:
                    with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as f:
                        page = f.read()
                except OSError:
                    return self._send(500, "text/plain", b"UI files are missing")
                page = page.replace("__PYDM_TOKEN__", srv.token).replace("__PYDM_VERSION__", VERSION)
                return self._send(200, MIME[".html"], page.encode(), {"Cache-Control": "no-store"})
            rel = path.lstrip("/")
            full = os.path.realpath(os.path.join(UI_DIR, rel))
            if not full.startswith(os.path.realpath(UI_DIR) + os.sep) or not os.path.isfile(full):
                return self._send(404, "text/plain", b"not found")
            with open(full, "rb") as f:
                data = f.read()
            cache = "public, max-age=86400" if full.endswith(".woff2") else "no-cache"
            self._send(200, MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream"),
                       data, {"Cache-Control": cache})

        do_HEAD = do_GET

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, "text/plain", b"forbidden")
            if not self._authed():
                return self._json({"error": "unauthorized"}, 401)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._json({"error": "too large"}, 413)
                body = json.loads(self.rfile.read(n) or b"{}")
                out = srv.handle(urllib.parse.urlparse(self.path).path, body)
            except (ValueError, KeyError, TypeError) as e:
                return self._json({"error": f"bad request: {e}"}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)[:200]}, 500)
            if out is None:
                return self._json({"error": "not found"}, 404)
            self._json(out)

    return Handler

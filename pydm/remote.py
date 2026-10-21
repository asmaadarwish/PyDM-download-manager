"""The window's view of the PyDM service: same calls as engine.Manager, over the local API.

All network work happens on background threads, so the window never waits on it.
"""

import datetime
import json
import threading
import urllib.error
import urllib.request


class Remote:
    def __init__(self, port, token):
        self.base = f"http://127.0.0.1:{port}"
        self.token = token
        self.settings = {"root": "", "max_concurrent": 3, "connections": 8, "quality": "best", "theme": "auto",
                         "language": "auto", "autostart": False}
        self.items = []
        self.queue_active = False
        self.start_at = None
        self.engine = ""
        self.show_seq = None
        self.ext_dir = ""
        self.fails = 0
        self.lost = False
        self.ready = False
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        threading.Thread(target=self._poll, daemon=True).start()

    # -- plumbing
    def _call(self, path, body=None, timeout=6):
        req = urllib.request.Request(self.base + path, headers={"X-PyDM-Token": self.token, "Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode(),
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def _async(self, path, body):
        def run():
            try:
                self._call(path, body)
            except (OSError, ValueError):
                pass
            self._wake.set()
        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        while not self._stop.is_set():
            try:
                st = self._call("/api/state", timeout=4)
                with self._lock:
                    self.items = st["items"]
                    self.settings = st["settings"]
                    self.queue_active = st["queue"]["active"]
                    sa = st["queue"]["start_at"]
                    self.start_at = datetime.datetime.fromisoformat(sa) if sa else None
                    self.engine, self.ext_dir, self.show_seq = st.get("engine", ""), st.get("extension_dir", ""), st.get("show_seq")
                self.fails = 0
                self.ready = True
            except (OSError, ValueError, KeyError):
                self.fails += 1
                if self.fails >= 4:
                    self.lost = True
            self._wake.wait(1.0)
            self._wake.clear()

    def refresh_soon(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    # -- what the window reads
    def snapshot(self):
        with self._lock:
            return list(self.items)

    def active_count(self):
        return sum(1 for i in self.snapshot() if i["status"] in ("queued", "probing", "downloading", "converting"))

    # -- what the window does (all fire-and-forget)
    def add_item(self, spec):
        self._async("/api/add", {"items": [spec]})

    def pause(self, dl_id):
        self._async("/api/item", {"id": dl_id, "action": "pause"})

    def resume(self, dl_id):
        self._async("/api/item", {"id": dl_id, "action": "resume"})

    def remove(self, dl_id, delete_files=False):
        self._async("/api/item", {"id": dl_id, "action": "remove", "delete_files": bool(delete_files)})

    def set_queue(self, on):
        self._async("/api/queue", {"action": "start" if on else "stop"})

    def schedule(self, hhmm):
        self._async("/api/schedule", {"time": hhmm})

    def clear_finished(self):
        self._async("/api/clear-finished", {})

    def set_settings(self, **kw):
        self.settings.update(kw)
        self._async("/api/settings", kw)

    def quit_service(self):
        try:
            self._call("/api/quit", {}, timeout=3)
        except (OSError, ValueError):
            pass

    def update_engine(self):
        r = self._call("/api/update-engine", {}, timeout=180)
        return r.get("version", "") if r.get("ok") else None

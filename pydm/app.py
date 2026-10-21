"""PyDM launcher.

  pythonw app.py              open PyDM (starts the background service if needed)
  pythonw app.py --background start only the background service (used at Windows start-up)
  pythonw app.py pydm://...   link from the browser extension
  pythonw app.py --quit       ask a running copy to close (used by the installer)
  pythonw app.py --ui PORT    (internal) the window, talking to the service on PORT

Two processes on purpose. The service owns the downloads, the tray icon and the local API.
The window is a separate process, so heavy downloading can never make it stutter, and closing
it never stops a download.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import shell   # noqa: E402

NO_CONSOLE = 0x08000000 if os.name == "nt" else 0


def _quiet_streams():
    """pythonw has no console: send prints / tracebacks to a log file."""
    if sys.stderr is not None and sys.stdout is not None:
        return
    try:
        os.makedirs(shell.home_dir(), exist_ok=True)
        log = open(os.path.join(shell.home_dir(), "pydm.log"), "a", encoding="utf-8", buffering=1)
    except OSError:
        log = open(os.devnull, "w")
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


class Service:
    """Downloads + local API + tray icon. Spawns the window on demand."""

    def __init__(self, keep_running):
        import engine
        import server
        self.keep = keep_running              # started at login: never exit by itself
        self.token = shell.load_token()
        self.mgr = engine.Manager()
        self.srv = server.PyDMServer(self.mgr, self.token, on_show=self.open_ui, on_quit=lambda: self.stop.set())
        self.stop = threading.Event()
        self.ui = None
        self.tray = None
        self.lock = threading.Lock()
        self.prev, self.known, self.ui_was_open = {}, set(), False
        self.watch_started = False
        if os.name == "nt":                   # the settings switch mirrors what Windows really has
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                    winreg.QueryValueEx(k, "PyDM")
                self.mgr.settings["autostart"] = True
            except OSError:
                self.mgr.settings["autostart"] = False

    # -- the window
    def ui_alive(self):
        return self.ui is not None and self.ui.poll() is None

    def open_ui(self, popup=None):
        if os.environ.get("PYDM_NO_WINDOW"):
            return
        with self.lock:
            if self.ui_alive():
                return                        # already open: the window notices the show counter and comes forward
            try:
                os.makedirs(shell.home_dir(), exist_ok=True)
                log = open(os.path.join(shell.home_dir(), "ui.log"), "a", encoding="utf-8", buffering=1)
                cmd = [sys.executable, os.path.join(HERE, "app.py"), "--ui", str(self.srv.port)]
                if popup:                     # hidden main window: only the progress / complete windows show
                    cmd += ["--popup", json.dumps(popup)]
                self.ui = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=NO_CONSOLE)
                log.close()
                self.ui_was_open = not popup
            except OSError as e:
                print("could not open the window:", repr(e))

    # -- tray
    def start_tray(self):
        try:
            import pystray
            from PIL import Image
            img = Image.open(os.path.join(HERE, "icons", "tray.png"))
            menu = pystray.Menu(pystray.MenuItem("Open PyDM", lambda *a: self.srv.handle("/api/show", {}), default=True),
                                pystray.MenuItem("Quit", lambda *a: self.stop.set()))
            self.tray = pystray.Icon("PyDM", img, "PyDM", menu)
            self.tray.run_detached()
        except Exception as e:  # noqa: BLE001 - tray is a nicety, never a blocker
            print("tray unavailable:", repr(e))
            self.tray = None

    def notify(self, title, text):
        if self.tray is not None:
            try:
                self.tray.notify(text[:200], title)
            except Exception:  # noqa: BLE001
                pass

    # -- main loop
    def run(self, show_window):
        self.srv.start()
        threading.Thread(target=self._prewarm, daemon=True).start()
        threading.Thread(target=self._remote_loop, daemon=True).start()
        if os.name == "nt":
            self.start_tray()
        if show_window:
            self.open_ui()
        try:
            while not self.stop.wait(1.0):
                self._watch()
        finally:
            self._cleanup()

    def _remote_loop(self):
        """Kill switch: if the owner turns PyDM off in status.json, pause everything, tell the user, and quit."""
        time.sleep(15)
        while not self.stop.is_set():
            st = shell.check_status()
            if shell.is_disabled(st):
                try:
                    for r in self.mgr.snapshot():
                        if r["status"] in ("queued", "probing", "downloading", "converting"):
                            self.mgr.pause(r["id"])
                    subprocess.Popen([sys.executable, os.path.join(HERE, "app.py"), "--disabled"], stdin=subprocess.DEVNULL,
                                     creationflags=NO_CONSOLE)
                except Exception:  # noqa: BLE001
                    pass
                self.stop.set()
                return
            self.stop.wait(6 * 3600)

    def _prewarm(self):
        """Import the video engine now, in the background, so the first link is not slow."""
        try:
            time.sleep(1.0)
            import yt_dlp  # noqa: F401
            import finder  # noqa: F401
        except Exception:  # noqa: BLE001
            pass

    def _watch(self):
        alive = self.ui_alive()
        if self.ui_was_open and not alive:
            self.ui_was_open = False
            if self.tray is not None and not self.mgr.settings.get("tray_hint"):
                self.mgr.settings["tray_hint"] = True
                self.mgr.save()
                self.notify("PyDM is still running", "Downloads continue. Click the icon near the clock to open it.")
        rows = self.mgr.snapshot()
        adds, dones = [], []
        for r in rows:
            rid, st = r["id"], r["status"]
            old = self.prev.get(rid)
            if self.watch_started:
                if st in ("probing", "downloading", "converting") and old not in ("probing", "downloading", "converting"):
                    adds.append(rid)
                elif old in ("queued", "probing", "downloading", "converting") and st == "completed" \
                        and self.mgr.settings.get("notify", True):
                    dones.append(rid)
            if st in ("probing", "downloading", "converting") or not self.watch_started:
                self.known.add(rid)
            self.prev[rid] = st
        self.watch_started = True
        if (adds or dones) and not alive:
            if os.environ.get("PYDM_NO_WINDOW") or self.mgr.settings.get("popups") is False:
                if self.tray is not None:
                    for rid in adds:
                        self.notify("Added to PyDM", next((r["name"] or r["url"] for r in rows if r["id"] == rid), ""))
                    for rid in dones:
                        self.notify("Download complete", next((r["name"] for r in rows if r["id"] == rid), ""))
            else:
                self.open_ui(popup={"add": adds, "done": dones})
        if not alive and not self.keep and self.tray is None and not self.ui_was_open and self.mgr.active_count() == 0 \
                and not os.environ.get("PYDM_NO_WINDOW"):
            self.stop.set()                   # no tray to reopen from and nothing running: exit

    def _cleanup(self):
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:  # noqa: BLE001
            pass
        if self.ui_alive():
            try:
                self.ui.terminate()
            except OSError:
                pass
        self.mgr.shutdown()
        self.srv.stop()


def ui_main(port, popup=None):
    """The window process (popup: started hidden, only to show progress / complete windows)."""
    _quiet_streams()
    try:
        import tkinter  # noqa: F401
        import gui
        from remote import Remote
    except ImportError as e:              # no tkinter: fall back to the web UI in a browser tab
        print("native window unavailable:", repr(e))
        import webbrowser
        webbrowser.open_new_tab(f"http://127.0.0.1:{port}/")
        return 0
    remote = Remote(port, shell.load_token())
    t0 = time.time()
    while not remote.ready and time.time() - t0 < 2.0:      # settings (dark mode) are needed before the first widget
        time.sleep(0.02)
    gui.apply_theme(remote.settings.get("theme") == "dark")
    win = gui.MainWindow(remote, popup)
    win.mainloop()
    return 0


def handle_protocol(port, token, links):
    """pydm://open  or  pydm://add?url=...&title=..."""
    for link in links:
        u = urllib.parse.urlparse(link)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.netloc == "add" and q.get("url"):
            shell.call(port, token, "/api/add", {"url": q["url"], "title": q.get("title", ""), "kind": q.get("kind", "auto")})
        else:
            shell.call(port, token, "/api/show")


def show_disabled():
    """Small message box: the owner has switched this app off."""
    import tkinter
    from tkinter import messagebox
    st = shell.cached_status()
    root = tkinter.Tk()
    root.withdraw()
    messagebox.showinfo("PyDM", st.get("message") or "PyDM has been discontinued and is no longer available.\n\nYour downloaded files are safe.")
    root.destroy()


def main(argv):
    _quiet_streams()
    if "--disabled" in argv:
        show_disabled()
        return 0
    if shell.is_disabled(shell.cached_status()) and "--quit" not in argv:       # was switched off earlier: stay off...
        if shell.is_disabled(shell.check_status() or shell.cached_status()):    # ...unless the owner switched it back on
            show_disabled()
            return 0
    if "--ui" in argv:
        popup = None
        if "--popup" in argv:
            try:
                popup = json.loads(argv[argv.index("--popup") + 1])
            except (ValueError, IndexError):
                popup = {}
        return ui_main(int(argv[argv.index("--ui") + 1]), popup)
    if "--quit" in argv:                          # used by the installer before replacing files
        running = shell.find_running()
        if running:
            try:
                shell.call(running, shell.load_token(), "/api/quit")
            except OSError:
                pass
        return 0
    background = "--background" in argv
    links = [a for a in argv if a.lower().startswith("pydm://")]
    running = shell.find_running()
    if running:                                   # already running: just bring the window up
        token = shell.load_token()
        try:
            if links:
                handle_protocol(running, token, links)
            elif not background:
                shell.call(running, token, "/api/show")
        except OSError:
            pass
        return 0
    svc = Service(keep_running=background)
    if links:
        threading.Timer(0.8, lambda: handle_protocol(svc.srv.port, svc.token, links)).start()
    svc.run(show_window=not background and not links)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# Releasing / controlling PyDM

PyDM reads `status.json` (main branch of this repo) at start and every few hours.

## Publish an update
1. Build the installer (`build/stage.sh`, then `makensis build/pydm.nsi`) and bump `VERSION` in `pydm/shell.py`.
2. GitHub → Releases → *Draft a new release* → tag `v3.x.y` → drag `PyDM-Setup.exe` → Publish.
3. Edit `status.json` on GitHub: set `"latest": "3.x.y"` and optionally `"notes"`. Users now get "PyDM x is available".

## Switch PyDM off for everyone (kill switch)
Edit `status.json`: `"enabled": false` and put a message in `"message"`.
Running copies pause downloads, show the message and quit; they stay off at next start.
Set it back to `true` to switch it on again. Works only on versions that include this feature (3.5.0 and later).

## How many downloads?
Releases page → each file shows its **download count**. (Installs that stay active are not tracked: PyDM sends no usage data.)

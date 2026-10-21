#!/bin/bash
# Assemble the Windows install tree in /home/claude/build/stage  (runtime/ + app/ + pydm.ico)
set -euo pipefail
SRC=/home/claude/work/src
RT=/home/claude/rt
ST=/home/claude/build/stage
rm -rf "$ST"; mkdir -p "$ST/runtime" "$ST/app/lib" "$ST/app/bin"

# ---- Python runtime (conda-forge win-64 CPython 3.12 + tcl/tk), trimmed
cp -a "$RT/winpy/." "$ST/runtime/"
cd "$ST/runtime"
rm -rf include libs Tools Scripts share conda-meta etc bin Library/include Library/share Library/ssl \
       Lib/test Lib/idlelib Lib/turtledemo Lib/lib2to3 Lib/ensurepip Lib/venv Lib/pydoc_data Lib/unittest/test \
       Lib/tkinter/test Lib/site-packages/* Lib/distutils/tests
find . -name '*.pdb' -delete
find . -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f DLLs/_test*.pyd DLLs/xxlimited*.pyd DLLs/_ctypes_test.pyd DLLs/*.ico LICENSE_PYTHON.txt
# DLLs that _tkinter / _ssl / _sqlite3 ... need, next to python.exe (found without PATH tricks)
for f in Library/bin/*.dll; do b=$(basename "$f"); [ -e "$b" ] || cp "$f" .; done
mkdir -p tcl
cp -a Library/lib/tcl8.6 tcl/tcl8.6; cp -a Library/lib/tk8.6 tcl/tk8.6
[ -d Library/lib/tcl8 ] && cp -a Library/lib/tcl8 tcl/tcl8
rm -rf Library
# tcl/tk: drop demos and message catalogs we never use
rm -rf tcl/tk8.6/demos tcl/tcl8.6/tzdata 2>/dev/null || true

# ---- app
cd "$SRC"
cp app.py engine.py finder.py gui.py remote.py server.py shell.py "$ST/app/"
cp -a ui "$ST/app/ui"; cp -a extension "$ST/app/extension"; rm -f "$ST/app/extension/config.json"
mkdir -p "$ST/app/icons"
cp icons/tb_*.png icons/tbd_*.png icons/s_*.png icons/sd_*.png icons/r_cat_*.png icons/logo.png icons/tray.png "$ST/app/icons/"
cat > "$ST/app/README.txt" <<'EOF'
PyDM - multi-connection download manager
Created by Asmaa Darwish - Content Me (http://asmaadarwish.com/)
EOF

# ---- libs (pure python + win wheels) and tools
for w in "$RT"/wheels/*.whl; do
  case "$w" in *python_xlib*|*imageio_ffmpeg*) continue;; esac
  unzip -q -o "$w" -d "$ST/app/lib"
done
rm -rf "$ST"/app/lib/*.dist-info "$ST"/app/lib/*.data
unzip -q -o -j "$RT/wheels/imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl" 'imageio_ffmpeg/binaries/*.exe' -d "$ST/app/bin"
mv "$ST"/app/bin/ffmpeg-win-x86_64-v7.1.exe "$ST/app/bin/ffmpeg.exe"
tar -xzf "$RT/npm/deno-win32-x64-2.9.6.tgz" -C /tmp package/deno.exe && mv /tmp/package/deno.exe "$ST/app/bin/deno.exe"

# ---- icon
python3 - <<'EOF'
from PIL import Image
im = Image.open("/home/claude/work/src/icons/logo.png").convert("RGBA")
im.save("/home/claude/build/stage/pydm.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
EOF
find "$ST/app" -name '__pycache__' -type d -prune -exec rm -rf {} +
du -sh "$ST"/runtime "$ST"/app "$ST"/app/bin "$ST"/app/lib; ls "$ST/app/lib" | head -30

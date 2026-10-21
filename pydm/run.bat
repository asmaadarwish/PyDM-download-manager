@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 app.py & goto :end)
python -c "import tkinter" >nul 2>nul && (python app.py & goto :end)
echo.
echo  Python is not installed (or tkinter is missing).
echo.
echo  1. Open https://www.python.org/downloads/ and download Python 3.12
echo  2. In the installer tick "Add python.exe to PATH"
echo  3. Keep "tcl/tk and IDLE" ticked, then finish
echo  4. Double-click run.bat again
echo.
pause
:end

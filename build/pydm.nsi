; PyDM installer  (built on Linux with makensis, no Python needed on the build or the target machine)
Unicode true
!define APP "PyDM"
!define VERSION "3.5.0"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\PyDM"

Name "${APP} ${VERSION}"
OutFile "PyDM-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\PyDM"
InstallDirRegKey HKCU "Software\PyDM" "InstallDir"
RequestExecutionLevel user          ; one user, no admin prompt
SetCompressor /SOLID lzma
SetCompressorDictSize 32
ShowInstDetails nevershow
BrandingText "PyDM ${VERSION} - Created by Asmaa Darwish - Content Me"

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define MUI_ICON "stage\pydm.ico"
!define MUI_UNICON "stage\pydm.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Open PyDM"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_LINK "Created by Asmaa Darwish - Content Me"
!define MUI_FINISHPAGE_LINK_LOCATION "http://asmaadarwish.com/"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; Ask a running PyDM (any version) to quit through its local API; no process is killed blindly.
!macro QuitBody
  InitPluginsDir
  FileOpen $0 "$PLUGINSDIR\quit.ps1" w
  FileWrite $0 "$$f = Join-Path $$env:USERPROFILE '.pydm\token'$\r$\n"
  FileWrite $0 "if (Test-Path $$f) { $$t = (Get-Content -Raw $$f).Trim(); 47321..47330 | ForEach-Object { try { Invoke-RestMethod -Method Post -Uri ('http://127.0.0.1:' + $$_ + '/api/quit') -Headers @{'X-PyDM-Token'=$$t} -Body '{}' -ContentType 'application/json' -TimeoutSec 2 | Out-Null } catch {} } }$\r$\n"
  FileClose $0
  nsExec::Exec 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$PLUGINSDIR\quit.ps1"'
  Pop $0
  Sleep 2500
!macroend

Function QuitRunning
  !insertmacro QuitBody
FunctionEnd

Function .onInit
  Call QuitRunning
FunctionEnd

Function LaunchApp
  Exec '"$INSTDIR\runtime\pythonw.exe" "$INSTDIR\app\app.py"'
FunctionEnd

Section "PyDM" SecMain
  SetOutPath "$INSTDIR"
  ; replace our own folders only (user data lives in %USERPROFILE%\.pydm and is never touched)
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime"
  File "stage\pydm.ico"
  SetOutPath "$INSTDIR\runtime"
  File /r "stage\runtime\*.*"
  SetOutPath "$INSTDIR\app"
  File /r "stage\app\*.*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\PyDM" "InstallDir" "$INSTDIR"

  ; shortcuts
  SetOutPath "$INSTDIR\app"
  CreateDirectory "$SMPROGRAMS\PyDM"
  CreateShortcut "$SMPROGRAMS\PyDM\PyDM.lnk" "$INSTDIR\runtime\pythonw.exe" '"$INSTDIR\app\app.py"' "$INSTDIR\pydm.ico" 0
  CreateShortcut "$SMPROGRAMS\PyDM\Uninstall PyDM.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\PyDM.lnk" "$INSTDIR\runtime\pythonw.exe" '"$INSTDIR\app\app.py"' "$INSTDIR\pydm.ico" 0

  ; start with Windows (quiet background service; the Settings switch controls this same value)
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "PyDM" '"$INSTDIR\runtime\pythonw.exe" "$INSTDIR\app\app.py" --background'

  ; pydm:// links (the browser extension uses them to wake PyDM up)
  WriteRegStr HKCU "Software\Classes\pydm" "" "URL:PyDM"
  WriteRegStr HKCU "Software\Classes\pydm" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\pydm\DefaultIcon" "" "$INSTDIR\pydm.ico"
  WriteRegStr HKCU "Software\Classes\pydm\shell\open\command" "" '"$INSTDIR\runtime\pythonw.exe" "$INSTDIR\app\app.py" "%1"'

  ; Apps & features entry
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "PyDM"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Asmaa Darwish"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\pydm.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Function un.onInit
  Call un.QuitRunning
FunctionEnd

Function un.QuitRunning
  !insertmacro QuitBody
FunctionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\PyDM\PyDM.lnk"
  Delete "$SMPROGRAMS\PyDM\Uninstall PyDM.lnk"
  RMDir "$SMPROGRAMS\PyDM"
  Delete "$DESKTOP\PyDM.lnk"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "PyDM"
  DeleteRegKey HKCU "Software\Classes\pydm"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\PyDM"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime"
  Delete "$INSTDIR\pydm.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd

; SimCoach setup wizard (NSIS 3, Modern UI 2). Installs for the current Windows user, no admin rights needed.
; Built by tools/installer/build_installer.sh, which passes VERSION (e.g. 6.11.1) and VIVERSION (6.11.1.0) and runs
; makensis in a folder holding this script, art\, LICENSE.txt and the app files.
; /S installs silently with every part except SimCast (no pages, SimCoach isn't started afterwards).

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user
ManifestDPIAware true

!ifndef VERSION
  !error "pass -DVERSION=x.y.z"
!endif
!ifndef VIVERSION
  !error "pass -DVIVERSION=x.y.z.w"
!endif

!define APP "SimCoach"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\SimCoach"
!define UNINSTALLER "Uninstall SimCoach.exe"
!define SIMCAST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\SimCast"
!define PS '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass'

Name "${APP}"
Caption "${APP} ${VERSION} Setup"
OutFile "SimCoach-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\SimCoach"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
BrandingText "SimCoach ${VERSION}"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VIVERSION}"
VIAddVersionKey "ProductName" "SimCoach"
VIAddVersionKey "FileDescription" "SimCoach Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "SimCoach"
VIAddVersionKey "LegalCopyright" "PolyForm Noncommercial License 1.0.0"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "Sections.nsh"

Var Partial
Var FinishText
Var SimCastResult       ; "" not asked for, "ok" installed, "failed" didn't install

!define MUI_ICON "SimCoach.ico"
!define MUI_UNICON "SimCoach.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "art\wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "art\wizard.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "art\header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "art\header.bmp"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Welcome to SimCoach ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "SimCoach is a live voice coach and race crew for sim racing: braking calls, \
corner-by-corner coaching, and an engineer, strategist and spotter on the radio.$\r$\n$\r$\n\
Setup installs it for your Windows account (no admin rights needed), then downloads Python, SimCoach's \
packages and the offline speech recognition: about 1 GB, a few minutes (less if SimCast is already \
installed: they share Python and packages). Keep the internet on.$\r$\n$\r$\n\
Already using SimCoach? Your reference laps, settings and reports are kept, and a SimCoach that's running is \
closed first (its session is saved).$\r$\n$\r$\nClick Next to continue."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!define MUI_COMPONENTSPAGE_SMALLDESC
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "SimCoach is installed"
!define MUI_FINISHPAGE_TEXT "$FinishText"
!define MUI_FINISHPAGE_RUN "$INSTDIR\SimCoach.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start SimCoach"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open the guide"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_LINK "SimCoach on GitHub"
!define MUI_FINISHPAGE_LINK_LOCATION "https://github.com/Jcedwar61/SimCoach"
!insertmacro MUI_PAGE_FINISH

!define MUI_UNCONFIRMPAGE_TEXT_TOP "SimCoach will be removed from this PC. Your reference laps, settings and \
reports are kept ($APPDATA\SimCoach and Documents\SimCoach Reports). If SimCoach is running it will be closed."
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------------------------------------------------------
Section "SimCoach" SecApp
  SectionIn RO
  SetShellVarContext current
  SetOutPath "$INSTDIR"

  DetailPrint "Closing SimCoach if it's running..."
  InitPluginsDir
  File "/oname=$PLUGINSDIR\install.ps1" "install.ps1"
  nsExec::ExecToLog '${PS} -File "$PLUGINSDIR\install.ps1" -Dest "$INSTDIR" -Step close'
  Pop $0

  DetailPrint "Copying SimCoach's files..."
  File "sim_coach.py"
  File "sim_coach.py.lock"
  File "SimCoach.exe"
  File "SimCoach.ico"
  File "SimCoach.bat"
  File "run_coach.bat"
  File "bind_push_to_talk.bat"
  File "README.txt"
  File "LICENSE.txt"
  File "install.ps1"
  ; SimCoach for SimHub: the plugin, the dashboard and their installer (simhub\install.ps1)
  SetOutPath "$INSTDIR\simhub"
  File "simhub\SimCoach.SimHub.dll"
  File "simhub\install.ps1"
  File "simhub\README.md"
  SetOutPath "$INSTDIR\simhub\dashboard\SimCoach"
  File "simhub\dashboard\SimCoach\SimCoach.djson"
  File "simhub\dashboard\SimCoach\SimCoach.djson.metadata"
  SetOutPath "$INSTDIR"
  ; left over from the older installer
  Delete "$INSTDIR\uninstall.ps1"
  Delete "$INSTDIR\SimCoach.exe.old"

  WriteUninstaller "$INSTDIR\${UNINSTALLER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "SimCoach"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "SimCoach"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\SimCoach.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "https://github.com/Jcedwar61/SimCoach"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\${UNINSTALLER}"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\${UNINSTALLER}" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntOp $0 $0 + 1000000
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" $0
SectionEnd

Section "Python, packages and speech recognition" SecParts
  SectionIn RO
  AddSize 1000000
  DetailPrint "Getting the Python runner (uv)..."
  nsExec::ExecToLog '${PS} -File "$INSTDIR\install.ps1" -Dest "$INSTDIR" -Step uv'
  Pop $0
  ${If} $0 != 0
    StrCpy $Partial 1
  ${EndIf}
  DetailPrint "Installing Python 3.12, SimCoach's packages and the offline speech recognition."
  DetailPrint "This takes a few minutes the first time; updates are quick..."
  Delete "$INSTDIR\setup-ready.txt"
  nsExec::ExecToLog '${PS} -File "$INSTDIR\install.ps1" -Dest "$INSTDIR" -Step parts'
  Pop $0
  ; finished only if the step says so with its file (a blocked or missing PowerShell can look like success)
  ${IfNot} ${FileExists} "$INSTDIR\setup-ready.txt"
    StrCpy $Partial 1
  ${EndIf}
  Delete "$INSTDIR\setup-ready.txt"
SectionEnd

Section "Desktop shortcut" SecDesktop
  SetShellVarContext current
  CreateShortcut "$DESKTOP\SimCoach.lnk" "$INSTDIR\SimCoach.exe" "" "$INSTDIR\SimCoach.ico" 0 SW_SHOWNORMAL "" \
    "SimCoach - live voice coach for sim racing"
SectionEnd

Section "Start menu shortcut" SecStart
  SetShellVarContext current
  CreateShortcut "$SMPROGRAMS\SimCoach.lnk" "$INSTDIR\SimCoach.exe" "" "$INSTDIR\SimCoach.ico" 0 SW_SHOWNORMAL "" \
    "SimCoach - live voice coach for sim racing"
SectionEnd

Section /o "SimCast: TV commentary for your race" SecSimCast
  AddSize 400000
  DetailPrint "Getting SimCast from GitHub (its own installer, run silently)..."
  nsExec::ExecToLog '${PS} -File "$INSTDIR\install.ps1" -Dest "$INSTDIR" -Step simcast'
  Pop $0
  ${If} $0 == 0
    StrCpy $SimCastResult "ok"
  ${Else}
    StrCpy $SimCastResult "failed"
  ${EndIf}
SectionEnd

Section "-finish"
  SetShellVarContext current
  ; a shortcut left unticked on an update is removed, so the choice sticks
  ${IfNot} ${SectionIsSelected} ${SecDesktop}
    Delete "$DESKTOP\SimCoach.lnk"
  ${EndIf}
  ${IfNot} ${SectionIsSelected} ${SecStart}
    Delete "$SMPROGRAMS\SimCoach.lnk"
  ${EndIf}
  ${If} $Partial == 1
    StrCpy $FinishText "SimCoach is installed, but some downloads didn't finish. SimCoach finishes them the \
first time it starts (keep the internet on). Details: install.log in the SimCoach folder."
  ${Else}
    StrCpy $FinishText "SimCoach is ready. Start it, press Start coaching, then drive in any supported sim.$\r$\n$\r$\n\
Using Assetto Corsa with Custom Shaders Patch? Restart the game once so it loads SimCoach's helper."
  ${EndIf}
  ${If} $SimCastResult == "ok"
    StrCpy $FinishText "$FinishText$\r$\n$\r$\nSimCast is installed too (Start menu). Run them together and its \
booth drops under the coach while the coach talks."
  ${ElseIf} $SimCastResult == "failed"
    StrCpy $FinishText "$FinishText$\r$\n$\r$\nSimCast couldn't be installed (details in install.log). Get it \
from github.com/Jcedwar61/SimCast."
  ${EndIf}
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} "SimCoach itself (required)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecParts} "Python 3.12, SimCoach's packages and the offline speech \
recognition, downloaded now (about 1 GB) so the first start is quick (required)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "A SimCoach icon on the desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStart} "SimCoach in the Start menu."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecSimCast} "Also install SimCast, a separate app: a TV commentary booth \
that calls your whole race and drops under the coach while it talks. Downloads its latest release from GitHub; \
it uses the same Python and packages, so it adds little."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  StrCpy $Partial 0
  StrCpy $SimCastResult ""
  ; SimCast already on this PC: offer to bring it up to its latest release instead (still unticked)
  ReadRegStr $0 HKCU "${SIMCAST_KEY}" "DisplayVersion"
  ${If} $0 != ""
    SectionSetText ${SecSimCast} "Update SimCast ($0 installed)"
  ${EndIf}
FunctionEnd

; ---------------------------------------------------------------------------------------------------------------
Section "Uninstall"
  SetShellVarContext current
  DetailPrint "Closing SimCoach if it's running..."
  IfFileExists "$INSTDIR\install.ps1" 0 +3
    nsExec::ExecToLog '${PS} -File "$INSTDIR\install.ps1" -Dest "$INSTDIR" -Step close'
    Pop $0
  Delete "$DESKTOP\SimCoach.lnk"
  Delete "$SMPROGRAMS\SimCoach.lnk"
  Delete "$INSTDIR\sim_coach.py"
  Delete "$INSTDIR\sim_coach.py.lock"
  Delete "$INSTDIR\SimCoach.exe"
  Delete "$INSTDIR\SimCoach.exe.old"
  Delete "$INSTDIR\SimCoach.ico"
  Delete "$INSTDIR\SimCoach.bat"
  Delete "$INSTDIR\run_coach.bat"
  Delete "$INSTDIR\bind_push_to_talk.bat"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\install.ps1"
  Delete "$INSTDIR\uninstall.ps1"
  Delete "$INSTDIR\install.log"
  Delete "$INSTDIR\setup-ready.txt"
  RMDir /r "$INSTDIR\__pycache__"
  RMDir /r "$INSTDIR\simhub"
  Delete "$INSTDIR\${UNINSTALLER}"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DetailPrint "SimCoach was removed. Your reference laps, settings and reports are kept."
SectionEnd

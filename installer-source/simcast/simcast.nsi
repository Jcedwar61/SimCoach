; SimCast setup wizard (NSIS 3, Modern UI 2). Installs for the current Windows user, no admin rights needed.
; Built by tools/installer/build_simcast_installer.sh, which passes VERSION and VIVERSION and runs makensis in a
; folder holding this script, art\, LICENSE.txt and the app files (simcast\ with its .py files and assets\).
; /S installs silently with every part.

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user
ManifestDPIAware true

!ifndef VERSION
  !error "pass -DVERSION=x.y"
!endif
!ifndef VIVERSION
  !error "pass -DVIVERSION=x.y.z.w"
!endif

!define APP "SimCast"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\SimCast"
!define UNINSTALLER "Uninstall SimCast.exe"
!define PS '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass'
!define DESC "SimCast - live TV-style race commentary"

Name "${APP}"
Caption "${APP} ${VERSION} Setup"
OutFile "SimCast-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\SimCast"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
BrandingText "SimCast ${VERSION}"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VIVERSION}"
VIAddVersionKey "ProductName" "SimCast"
VIAddVersionKey "FileDescription" "SimCast Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "SimCast"
VIAddVersionKey "LegalCopyright" "MIT License"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "Sections.nsh"

Var Partial
Var FinishText

!define MUI_ICON "SimCast.ico"
!define MUI_UNICON "SimCast.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "art\wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "art\wizard.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "art\header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "art\header.bmp"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Welcome to SimCast ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "SimCast gives your sim race the television treatment: a commentary booth calls the \
whole race live while you drive, from the start to the chequered flag, for every car on the grid.$\r$\n$\r$\n\
Setup installs it for your Windows account (no admin rights needed), then downloads Python and SimCast's \
packages: a few minutes the first time. Keep the internet on.$\r$\n$\r$\n\
Your settings are kept if SimCast is already installed.$\r$\n$\r$\nClick Next to continue."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!define MUI_COMPONENTSPAGE_SMALLDESC
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "SimCast is installed"
!define MUI_FINISHPAGE_TEXT "$FinishText"
!define MUI_FINISHPAGE_RUN "$INSTDIR\SimCast.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start SimCast"
!define MUI_FINISHPAGE_LINK "The SimCast guide"
!define MUI_FINISHPAGE_LINK_LOCATION "https://github.com/Jcedwar61/SimCoach/blob/main/SIMCAST.md"
!insertmacro MUI_PAGE_FINISH

!define MUI_UNCONFIRMPAGE_TEXT_TOP "SimCast will be removed from this PC. Your settings are kept \
($APPDATA\SimCast). If SimCast is running it will be closed."
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------------------------------------------------------
Section "SimCast" SecApp
  SectionIn RO
  SetShellVarContext current
  SetOutPath "$INSTDIR"

  DetailPrint "Closing SimCast if it's running..."
  InitPluginsDir
  File "/oname=$PLUGINSDIR\install.ps1" "install.ps1"
  nsExec::ExecToLog '${PS} -File "$PLUGINSDIR\install.ps1" -Dest "$INSTDIR" -Step close'
  Pop $0

  DetailPrint "Copying SimCast's files..."
  File "sim_cast.py"
  File "sim_coach.py"
  File "SimCast.exe"
  File "SimCast.ico"
  File "SimCast.bat"
  File "LICENSE.txt"
  File "install.ps1"
  RMDir /r "$INSTDIR\simcast"
  SetOutPath "$INSTDIR\simcast"
  File "simcast\*.py"
  SetOutPath "$INSTDIR\simcast\assets"
  File "simcast\assets\*.png"
  SetOutPath "$INSTDIR"

  WriteUninstaller "$INSTDIR\${UNINSTALLER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "SimCast"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "SimCast"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\SimCast.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "https://github.com/Jcedwar61/SimCoach/blob/main/SIMCAST.md"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\${UNINSTALLER}"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\${UNINSTALLER}" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntOp $0 $0 + 250000
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" $0
SectionEnd

Section "Python and packages" SecParts
  SectionIn RO
  AddSize 250000
  DetailPrint "Getting the Python runner (uv)..."
  nsExec::ExecToLog '${PS} -File "$INSTDIR\install.ps1" -Dest "$INSTDIR" -Step uv'
  Pop $0
  ${If} $0 != 0
    StrCpy $Partial 1
  ${EndIf}
  DetailPrint "Installing Python 3.12 and SimCast's packages (a few minutes the first time)..."
  Delete "$INSTDIR\setup-ready.txt"
  nsExec::ExecToLog '${PS} -File "$INSTDIR\install.ps1" -Dest "$INSTDIR" -Step parts'
  Pop $0
  ${IfNot} ${FileExists} "$INSTDIR\setup-ready.txt"
    StrCpy $Partial 1
  ${EndIf}
  Delete "$INSTDIR\setup-ready.txt"
SectionEnd

Section "Desktop shortcut" SecDesktop
  SetShellVarContext current
  CreateShortcut "$DESKTOP\SimCast.lnk" "$INSTDIR\SimCast.exe" "" "$INSTDIR\SimCast.ico" 0 SW_SHOWNORMAL "" "${DESC}"
SectionEnd

Section "Start menu shortcut" SecStart
  SetShellVarContext current
  CreateShortcut "$SMPROGRAMS\SimCast.lnk" "$INSTDIR\SimCast.exe" "" "$INSTDIR\SimCast.ico" 0 SW_SHOWNORMAL "" "${DESC}"
SectionEnd

Section "-finish"
  SetShellVarContext current
  ${IfNot} ${SectionIsSelected} ${SecDesktop}
    Delete "$DESKTOP\SimCast.lnk"
  ${EndIf}
  ${IfNot} ${SectionIsSelected} ${SecStart}
    Delete "$SMPROGRAMS\SimCast.lnk"
  ${EndIf}
  ${If} $Partial == 1
    StrCpy $FinishText "SimCast is installed, but some downloads didn't finish. SimCast finishes them the first \
time it starts (keep the internet on). Details: install.log in the SimCast folder."
  ${Else}
    StrCpy $FinishText "SimCast is ready. Start it and click Demo race to hear the booth, or just start a race in \
your sim: SimCast goes on air by itself.$\r$\n$\r$\nAssetto Corsa: switch on the CrewChiefEx app so SimCast can see the \
other cars."
  ${EndIf}
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} "SimCast itself (required)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecParts} "Python 3.12 and SimCast's packages, downloaded now so the first \
start is quick (required)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "A SimCast icon on the desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStart} "SimCast in the Start menu."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  StrCpy $Partial 0
FunctionEnd

; ---------------------------------------------------------------------------------------------------------------
Section "Uninstall"
  SetShellVarContext current
  DetailPrint "Closing SimCast if it's running..."
  IfFileExists "$INSTDIR\install.ps1" 0 +3
    nsExec::ExecToLog '${PS} -File "$INSTDIR\install.ps1" -Dest "$INSTDIR" -Step close'
    Pop $0
  Delete "$DESKTOP\SimCast.lnk"
  Delete "$SMPROGRAMS\SimCast.lnk"
  Delete "$INSTDIR\sim_cast.py"
  Delete "$INSTDIR\sim_coach.py"
  Delete "$INSTDIR\SimCast.exe"
  Delete "$INSTDIR\SimCast.ico"
  Delete "$INSTDIR\SimCast.bat"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\install.ps1"
  Delete "$INSTDIR\install.log"
  Delete "$INSTDIR\setup-ready.txt"
  RMDir /r "$INSTDIR\simcast"
  RMDir /r "$INSTDIR\__pycache__"
  Delete "$INSTDIR\${UNINSTALLER}"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DetailPrint "SimCast was removed. Your settings are kept."
SectionEnd

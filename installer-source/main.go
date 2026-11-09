// SimCoach-Setup.exe: installs SimCoach for the current Windows user (no admin rights) into
// %LOCALAPPDATA%\Programs\SimCoach, then runs install.ps1 (shortcuts, Apps entry, Python parts).
// Pass --silent to install without dialogs and without starting SimCoach afterwards.
//go:build windows

package main

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

const title = "SimCoach Setup"

const (
	mbOK          = 0x0
	mbYesNo       = 0x4
	mbIconInfo    = 0x40
	mbIconWarning = 0x30
	mbIconError   = 0x10
	mbIconQuery   = 0x20
	idYes         = 6

	createNewConsole = 0x00000010
	detachedProcess  = 0x00000008
)

var messageBox = syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")

func msgBox(text string, flags uintptr) int {
	t, _ := syscall.UTF16PtrFromString(text)
	c, _ := syscall.UTF16PtrFromString(title)
	r, _, _ := messageBox.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), flags|0x00010000) // MB_SETFOREGROUND
	return int(r)
}

func launch(dest string) {
	cmd := exec.Command(filepath.Join(dest, "SimCoach.exe"))
	cmd.Dir = dest
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: detachedProcess}
	_ = cmd.Start()
}

func main() {
	silent := false
	for _, a := range os.Args[1:] {
		if strings.EqualFold(a, "--silent") || strings.EqualFold(a, "/silent") {
			silent = true
		}
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		if !silent {
			msgBox("Couldn't find your local app data folder.", mbOK|mbIconError)
		}
		os.Exit(1)
	}
	dest := filepath.Join(local, "Programs", "SimCoach")

	if !silent {
		intro := "SimCoach will be installed for your Windows account (no admin rights needed):\n\n    " + dest +
			"\n\n  •  Desktop and Start menu shortcuts" +
			"\n  •  Setup then downloads Python 3.12, SimCoach's packages and the offline speech model" +
			"\n  •  Uninstall any time from Settings > Apps > Installed apps" +
			"\n\nYour reference laps, settings and reports are kept if you already use SimCoach. " +
			"A SimCoach that's running is closed first (its session is saved).\n\nInstall now?"
		if msgBox(intro, mbYesNo|mbIconQuery) != idYes {
			return
		}
	}

	if err := unpack(dest); err != nil {
		if !silent {
			msgBox("Couldn't copy SimCoach's files to\n"+dest+"\n\n"+err.Error()+"\n\nYou can run SimCoach-Setup.exe again.", mbOK|mbIconError)
		}
		os.Exit(1)
	}

	ps := filepath.Join(os.Getenv("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	if _, err := os.Stat(ps); err != nil {
		ps = "powershell.exe"
	}
	cmd := exec.Command(ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
		filepath.Join(dest, "install.ps1"), "-Dest", dest)
	cmd.Dir = dest
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNewConsole}
	code := 0
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			code = ee.ExitCode()
		} else {
			code = 1
		}
	}
	if silent {
		os.Exit(code)
	}
	logPath := filepath.Join(dest, "install.log")
	switch code {
	case 0:
		if msgBox("SimCoach is installed.\n\nIt's on your desktop and in the Start menu.\n\nStart SimCoach now?", mbYesNo|mbIconInfo) == idYes {
			launch(dest)
		}
	case 2:
		if msgBox("SimCoach is installed, but some parts didn't finish downloading.\n"+
			"They'll finish the first time you start it (keep the internet on).\n\nDetails: "+logPath+
			"\n\nStart SimCoach now?", mbYesNo|mbIconWarning) == idYes {
			launch(dest)
		}
	default:
		msgBox("SimCoach setup didn't finish.\n\nDetails: "+logPath+"\n\nYou can run SimCoach-Setup.exe again.", mbOK|mbIconError)
		os.Exit(1)
	}
}

// SimCast.exe: starts SimCast (sim_cast.py, next to this .exe) with uv's windowless Python runner, so there's
// no console window. If uv isn't installed yet it runs SimCast.bat instead, which gets uv and starts SimCast
// in a console the first time. Build: tools/launcher/build_launcher.sh
//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

const appName = "SimCast"

var (
	user32      = syscall.NewLazyDLL("user32.dll")
	messageBoxW = user32.NewProc("MessageBoxW")
)

func message(text string, icon uintptr) {
	t, _ := syscall.UTF16PtrFromString(text)
	c, _ := syscall.UTF16PtrFromString(appName)
	messageBoxW.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), icon)
}

func findUVW() string {
	if p, err := exec.LookPath("uvw.exe"); err == nil {
		return p
	}
	home := os.Getenv("USERPROFILE")
	for _, d := range []string{filepath.Join(home, ".local", "bin"), filepath.Join(home, ".cargo", "bin")} {
		p := filepath.Join(d, "uvw.exe")
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return ""
}

func main() {
	exe, err := os.Executable()
	if err != nil {
		message("SimCast couldn't find its own folder: "+err.Error(), 0x10)
		os.Exit(1)
	}
	dir := filepath.Dir(exe)
	script := filepath.Join(dir, "sim_cast.py")
	if _, err := os.Stat(script); err != nil {
		message("sim_cast.py is missing from "+dir+".\n\nReinstall SimCast with SimCast-Setup.exe.", 0x10)
		os.Exit(1)
	}
	args := os.Args[1:]
	uvw := findUVW()
	if uvw == "" {
		// First run without the installer: the batch file downloads uv, then starts SimCast in a console.
		bat := filepath.Join(dir, "SimCast.bat")
		cmd := exec.Command("cmd.exe", append([]string{"/c", bat}, args...)...)
		cmd.Dir = dir
		if err := cmd.Start(); err != nil {
			message("SimCast couldn't start: "+err.Error(), 0x10)
			os.Exit(1)
		}
		return
	}
	cmd := exec.Command(uvw, append([]string{"run", "--python", "3.12", script}, args...)...)
	cmd.Dir = dir
	start := time.Now()
	err = cmd.Run()
	if err != nil && time.Since(start) < 20*time.Second {
		log := filepath.Join(os.Getenv("APPDATA"), "SimCast", "simcast.log")
		message(fmt.Sprintf("SimCast stopped while starting (%v).\n\nRun SimCast.bat to see what went wrong, "+
			"or look in %s.", err, log), 0x30)
		os.Exit(1)
	}
}

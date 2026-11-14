// SimCast.exe: starts SimCast (sim_cast.py, next to this .exe) without a console window.
//
// It needs nothing else on the PC: if uv (the Python runner, github.com/astral-sh/uv) isn't there yet, it
// downloads it into %USERPROFILE%\.local\bin, the folder uv's own installer uses. The first start shows a
// console while uv fetches Python 3.12 and SimCast's packages (a few minutes, once); after that SimCast starts
// straight into its window.
//
//	SimCast.exe [SimCast options]   start SimCast
//	SimCast.exe --setup             get uv, Python and the packages, print progress, exit (the installer runs this)
//
// No PowerShell, so it works the same under Wine/Proton. Build: tools/launcher/build_launcher.sh
//go:build windows

package main

import (
	"archive/zip"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	appName       = "SimCast"
	createConsole = 0x00000010
	readyFile     = "setup-ready.txt"
)

var (
	user32      = syscall.NewLazyDLL("user32.dll")
	messageBoxW = user32.NewProc("MessageBoxW")
)

func message(text string, icon uintptr) {
	t, _ := syscall.UTF16PtrFromString(text)
	c, _ := syscall.UTF16PtrFromString(appName)
	messageBoxW.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), icon)
}

func uvBin() string {
	return filepath.Join(os.Getenv("USERPROFILE"), ".local", "bin")
}

func findUV(name string) string {
	if p, err := exec.LookPath(name); err == nil {
		return p
	}
	home := os.Getenv("USERPROFILE")
	for _, d := range []string{uvBin(), filepath.Join(home, ".cargo", "bin")} {
		p := filepath.Join(d, name)
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return ""
}

// downloadUV fetches uv's official Windows release zip and unpacks uv.exe, uvw.exe and uvx.exe.
func downloadUV(log func(string)) error {
	arch := "x86_64"
	if runtime.GOARCH == "arm64" || strings.EqualFold(os.Getenv("PROCESSOR_ARCHITECTURE"), "ARM64") {
		arch = "aarch64"
	}
	url := "https://github.com/astral-sh/uv/releases/latest/download/uv-" + arch + "-pc-windows-msvc.zip"
	log("Downloading uv (the Python runner) from github.com/astral-sh/uv ...")
	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("download failed: %s", resp.Status)
	}
	tmp, err := os.CreateTemp("", "simcast-uv-*.zip")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := io.Copy(tmp, resp.Body); err != nil {
		tmp.Close()
		return err
	}
	tmp.Close()
	zr, err := zip.OpenReader(tmp.Name())
	if err != nil {
		return err
	}
	defer zr.Close()
	if err := os.MkdirAll(uvBin(), 0o755); err != nil {
		return err
	}
	n := 0
	for _, f := range zr.File {
		base := filepath.Base(f.Name)
		if base != "uv.exe" && base != "uvw.exe" && base != "uvx.exe" {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		out, err := os.Create(filepath.Join(uvBin(), base))
		if err != nil {
			rc.Close()
			return err
		}
		_, err = io.Copy(out, rc)
		rc.Close()
		out.Close()
		if err != nil {
			return err
		}
		n++
	}
	if n == 0 {
		return fmt.Errorf("uv.exe wasn't in the download")
	}
	log("uv is ready: " + uvBin())
	return nil
}

func ensureUV(log func(string)) (string, error) {
	if p := findUV("uv.exe"); p != "" {
		return p, nil
	}
	if err := downloadUV(log); err != nil {
		return "", err
	}
	if p := findUV("uv.exe"); p != "" {
		return p, nil
	}
	return "", fmt.Errorf("uv.exe still not found after downloading it")
}

// setup gets everything SimCast needs. console: show it in a console window of its own (a first start without
// the installer), else print into this process's output (the installer's progress list).
func setup(dir string, console bool) error {
	log := func(s string) { fmt.Println(s) }
	uv, err := ensureUV(log)
	if err != nil {
		return err
	}
	cmd := exec.Command(uv, "run", "--python", "3.12", filepath.Join(dir, "sim_cast.py"), "--setup")
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "NO_COLOR=1")
	if console {
		cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createConsole}
	} else {
		cmd.Env = append(cmd.Env, "UV_NO_PROGRESS=1")
		cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	}
	log("Getting Python 3.12 and SimCast's packages (a few minutes the first time) ...")
	if err := cmd.Run(); err != nil {
		return err
	}
	_ = os.WriteFile(filepath.Join(dir, readyFile), []byte("ok\n"), 0o644)
	log("SimCast is ready.")
	return nil
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
	if len(args) > 0 && args[0] == "--setup" {
		if err := setup(dir, false); err != nil {
			fmt.Println("Setup didn't finish: " + err.Error() + " (SimCast finishes it the first time it starts).")
			os.Exit(2)
		}
		return
	}
	if _, err := os.Stat(filepath.Join(dir, readyFile)); err != nil {
		if err := setup(dir, true); err != nil {
			message("SimCast couldn't get ready: "+err.Error()+"\n\nCheck the internet connection and start SimCast again.", 0x10)
			os.Exit(1)
		}
	}
	uvw := findUV("uvw.exe")
	if uvw == "" {
		message("uvw.exe (part of uv) wasn't found. Start SimCast again, or reinstall it.", 0x10)
		os.Exit(1)
	}
	cmd := exec.Command(uvw, append([]string{"run", "--python", "3.12", script}, args...)...)
	cmd.Dir = dir
	start := time.Now()
	err = cmd.Run()
	if err != nil && time.Since(start) < 20*time.Second {
		log := filepath.Join(os.Getenv("APPDATA"), "SimCast", "simcast.log")
		message(fmt.Sprintf("SimCast stopped while starting (%v).\n\nDetails are in %s. Running SimCast.bat "+
			"shows them too.", err, log), 0x30)
		os.Exit(1)
	}
}

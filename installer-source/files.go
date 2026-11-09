package main

import (
	"embed"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

//go:embed payload
var payload embed.FS

// writeFile replaces dst. A file that's in use (SimCoach.exe while SimCoach runs) can't be overwritten on
// Windows but can be renamed, so it's moved to .old first; install.ps1 deletes that once SimCoach is closed.
func writeFile(dst string, data []byte) error {
	tmp := dst + ".new"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	if err := os.Rename(tmp, dst); err == nil {
		return nil
	}
	old := dst + ".old"
	_ = os.Remove(old)
	if err := os.Rename(dst, old); err != nil && !errors.Is(err, fs.ErrNotExist) {
		_ = os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, dst)
}

func unpack(dest string) error {
	if err := os.MkdirAll(dest, 0o755); err != nil {
		return err
	}
	return fs.WalkDir(payload, "payload", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel := strings.TrimPrefix(strings.TrimPrefix(p, "payload"), "/")
		if rel == "" {
			return nil
		}
		dst := filepath.Join(dest, filepath.FromSlash(rel))
		if d.IsDir() {
			return os.MkdirAll(dst, 0o755)
		}
		data, err := payload.ReadFile(p)
		if err != nil {
			return err
		}
		return writeFile(dst, data)
	})
}

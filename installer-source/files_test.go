package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestUnpackFreshAndOverwrite(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "Programs", "SimCoach")
	if err := unpack(dest); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{"sim_coach.py", "install.ps1", "uninstall.ps1", "SimCoach.exe", "SimCoach.ico", "SimCoach.bat", "README.txt", "run_coach.bat", "bind_push_to_talk.bat"} {
		want, _ := payload.ReadFile("payload/" + f)
		got, err := os.ReadFile(filepath.Join(dest, f))
		if err != nil || string(got) != string(want) {
			t.Fatalf("%s not unpacked correctly (err=%v)", f, err)
		}
	}
	// an update over an existing install replaces the files and leaves no temp files behind
	os.WriteFile(filepath.Join(dest, "sim_coach.py"), []byte("old"), 0o644)
	if err := unpack(dest); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(filepath.Join(dest, "sim_coach.py"))
	want, _ := payload.ReadFile("payload/sim_coach.py")
	if string(got) != string(want) {
		t.Fatal("sim_coach.py not replaced")
	}
	ents, _ := os.ReadDir(dest)
	for _, e := range ents {
		if filepath.Ext(e.Name()) == ".new" {
			t.Fatal("left temp file", e.Name())
		}
	}
}

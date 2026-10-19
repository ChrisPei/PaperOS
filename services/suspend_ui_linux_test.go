package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestSuspendSelectsInstalledLauncherChild(t *testing.T) {
	proc := t.TempDir()
	process := func(pid, parent int, exe, comm, started string) {
		t.Helper()
		dir := filepath.Join(proc, strconv.Itoa(pid))
		if err := os.MkdirAll(dir, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(exe, filepath.Join(dir, "exe")); err != nil {
			t.Fatal(err)
		}
		fields := strings.Fields("S " + strconv.Itoa(parent) + strings.Repeat(" 0", 18))
		fields[19] = started
		if err := os.WriteFile(filepath.Join(dir, "stat"), []byte(fmt.Sprintf("%d (%s) %s\n", pid, comm, strings.Join(fields, " "))), 0600); err != nil {
			t.Fatal(err)
		}
	}
	process(100, 1, "/usr/bin/paperos", "paperos", "10")
	process(200, 1, "/usr/sbin/dropbear", "dropbear", "20")
	for i, test := range []struct {
		name, exe, comm string
		parent          int
		selected        bool
	}{
		{"installed game", "/var/lib/paperos/apps/org.paperos.ace-attorney-1/paperos-nds", "paperos-nds", 100, true},
		{"nested executable", "/var/lib/paperos/apps/org.paperos.other/bin/ui", "ui", 100, true},
		{"comm delimiter", "/var/lib/paperos/apps/org.paperos.other/ui", "odd ) name", 100, true},
		{"SSH launched app", "/var/lib/paperos/apps/org.paperos.other/ui", "ui", 200, false},
		{"system service", "/usr/sbin/paperos-services", "services", 100, false},
		{"prefix lookalike", "/var/lib/paperos/apps-other/ui", "ui", 100, false},
		{"data executable", "/var/lib/paperos/apps/.data/other/ui", "ui", 100, false},
		{"deleted app", "/var/lib/paperos/apps/org.paperos.other/ui (deleted)", "ui", 100, false},
		{"missing parent", "/var/lib/paperos/apps/org.paperos.other/ui", "ui", 999, false},
	} {
		pid := 300 + i
		process(pid, test.parent, test.exe, test.comm, "123456")
		state, start, okay := uiProcessAt(proc, pid)
		if okay != test.selected || (okay && (state != "S" || start != "123456")) {
			t.Errorf("%s: %q %q %t", test.name, state, start, okay)
		}
	}
	if _, _, okay := uiProcessAt(proc, 100); !okay {
		t.Fatal("launcher not selected")
	}
	if _, _, okay := uiProcessAt(proc, 200); okay {
		t.Fatal("SSH daemon selected")
	}
}

// Opt-in hardware QA only. Pauses the existing UI and installed foreground for
// less than one second; does not blank the screen or suspend the kernel.
func TestDeviceInstalledUIStopResume(t *testing.T) {
	pid, err := strconv.Atoi(os.Getenv("PAPEROS_TEST_FOREGROUND_PID"))
	if err != nil {
		t.Skip("physical-device PID not supplied")
	}
	_, start, okay := uiProcess(pid)
	if !okay {
		t.Fatal("foreground not recognized")
	}
	stopped, err := stopSleepUI()
	defer resumeSleepUI(stopped)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, item := range stopped {
		if item.pid == pid && item.start == start {
			found = true
		}
	}
	state, current, okay := uiProcess(pid)
	if !found || !okay || current != start || (state != "T" && state != "t") {
		t.Fatal("game display did not stop", found, state, current)
	}
	resumeSleepUI(stopped)
	state, current, okay = uiProcess(pid)
	if !okay || current != start || state == "T" || state == "t" {
		t.Fatal("game display did not resume", state, current)
	}
	t.Logf("PAPEROS_FOREGROUND_SUSPEND_TEST pid=%d processes=%d passed", pid, len(stopped))
}

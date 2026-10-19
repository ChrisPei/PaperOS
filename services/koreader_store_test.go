package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// Opt-in release test: exercise the complete 41 MiB production archive through
// the real Go downloader/extractor and C installer in an empty application root.
func TestKOReaderFullStorePackageFreshInstall(t *testing.T) {
	archive := os.Getenv("PAPEROS_KOREADER_STORE_PACKAGE")
	if archive == "" {
		t.Skip("set PAPEROS_KOREADER_STORE_PACKAGE to the release .papp.tar.gz")
	}
	data, e := os.ReadFile(archive)
	if e != nil {
		t.Fatal(e)
	}
	sum := sha256.Sum256(data)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.ServeFile(w, r, archive) }))
	defer server.Close()
	s := storeTestService(t)
	s.storeInstaller, e = filepath.Abs("../build/host/paperos")
	if e != nil {
		t.Fatal(e)
	}
	id := "org.paperos.koreader"
	var release struct {
		Version string `json:"port_version"`
	}
	pin, e := os.ReadFile("../os/koreader-release.json")
	if e != nil {
		t.Fatal(e)
	}
	if e = json.Unmarshal(pin, &release); e != nil || release.Version == "" {
		t.Fatal("invalid release pin", e)
	}
	// Data can survive removal and must also survive a fresh reinstallation.
	marker := filepath.Join(s.apps, ".data", id, "reading-marker")
	if e = os.MkdirAll(filepath.Dir(marker), 0700); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(marker, []byte("existing reading profile"), 0600); e != nil {
		t.Fatal(e)
	}
	s.store.Entries = []StoreEntry{{Key: "test:" + id, ID: id, Name: "KOReader", Version: release.Version, Kind: "papp", SourceID: "test", URL: server.URL, SHA256: hex.EncodeToString(sum[:])}}
	wait := func() StoreJob {
		t.Helper()
		for until := time.Now().Add(45 * time.Second); time.Now().Before(until); time.Sleep(10 * time.Millisecond) {
			s.mu.Lock()
			busy := s.store.Busy
			var j StoreJob
			if s.store.Job != nil {
				j = *s.store.Job
			}
			s.mu.Unlock()
			if !busy {
				return j
			}
		}
		t.Fatal("full package operation timed out")
		return StoreJob{}
	}
	mustCommand(t, s, "store-download", "key", "test:"+id)
	job := wait()
	if job.Phase != "ready" {
		t.Fatal(job.Message)
	}
	if _, e = os.Stat(filepath.Join(s.apps, id)); !os.IsNotExist(e) {
		t.Fatal("download installed without confirmation")
	}
	mustCommand(t, s, "store-install", "id", job.ID, "digest", job.Digest)
	job = wait()
	if job.Phase != "done" {
		t.Fatal(job.Message)
	}
	for _, name := range []string{"run.sh", "paperos-overlay"} {
		info, e := os.Stat(filepath.Join(s.apps, id, name))
		if e != nil || info.Mode()&0111 == 0 {
			t.Fatalf("missing executable %s: %v", name, e)
		}
	}
	for _, name := range []string{"runtime.ext3.gz", "runtime.sha256", "SOURCES.md", "KOReader-COPYING.txt", "PaperOS-COPYING.txt"} {
		if _, e = os.Stat(filepath.Join(s.apps, id, name)); e != nil {
			t.Fatal(name, e)
		}
	}
	saved, e := os.ReadFile(marker)
	if e != nil || string(saved) != "existing reading profile" {
		t.Fatal("fresh installation replaced existing reading data")
	}
}

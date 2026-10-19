package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/klauspost/compress/zstd"
)

func storeFixture(t *testing.T, kind, version string) []byte {
	t.Helper()
	var b bytes.Buffer
	z := zip.NewWriter(&b)
	files := map[string]string{"app.papp/manifest.conf": "id=org.paperos.store-test\nname=Store test\nversion=" + version + "\nexec=run.sh\n", "app.papp/run.sh": "#!/bin/sh\nexit 0\n"}
	if kind == "koplugin" {
		files = map[string]string{"example.koplugin/_meta.lua": "return {name='example'}", "example.koplugin/main.lua": "return {}", "example.koplugin/example_configuration.lua": "return {}"}
	}
	for name, data := range files {
		h := &zip.FileHeader{Name: name, Method: zip.Deflate}
		h.SetMode(0755)
		w, e := z.CreateHeader(h)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = w.Write([]byte(data)); e != nil {
			t.Fatal(e)
		}
	}
	if e := z.Close(); e != nil {
		t.Fatal(e)
	}
	return b.Bytes()
}
func storeTestService(t *testing.T) *Service {
	s := testService(t)
	s.loadStore()
	s.store.Sources = []StoreSource{{ID: "test", Name: "Test", Enabled: true}}
	return s
}
func storeWait(t *testing.T, s *Service) StoreJob {
	t.Helper()
	for end := time.Now().Add(8 * time.Second); time.Now().Before(end); time.Sleep(time.Millisecond * 5) {
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
	t.Fatal("store operation did not finish")
	return StoreJob{}
}
func storeServePackage(t *testing.T, s *Service, body []byte, version, kind string) func() {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write(body) }))
	sum := sha256.Sum256(body)
	s.mu.Lock()
	s.store.Entries = []StoreEntry{{Key: "test:org.paperos.store-test", ID: "org.paperos.store-test", Name: "Test", Version: version, Kind: kind, URL: server.URL, SHA256: hex.EncodeToString(sum[:]), SourceID: "test"}}
	s.mu.Unlock()
	return server.Close
}
func TestStoreArchiveFormatsAndChecksums(t *testing.T) {
	var tarBytes bytes.Buffer
	tw := tar.NewWriter(&tarBytes)
	data := []byte("hello")
	_ = tw.WriteHeader(&tar.Header{Name: "x/main.lua", Mode: 0644, Size: int64(len(data))})
	_, _ = tw.Write(data)
	_ = tw.Close()
	var gz bytes.Buffer
	g := gzip.NewWriter(&gz)
	_, _ = g.Write(tarBytes.Bytes())
	_ = g.Close()
	var zs bytes.Buffer
	z, e := zstd.NewWriter(&zs, zstd.WithEncoderConcurrency(1))
	if e != nil {
		t.Fatal(e)
	}
	_, _ = z.Write(tarBytes.Bytes())
	_ = z.Close()
	formats := map[string][]byte{"zip": storeFixture(t, "papp", "1.0"), "tar": tarBytes.Bytes(), "tgz": gz.Bytes(), "kpkg-zstd": zs.Bytes()}
	for name, data := range formats {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			p := filepath.Join(dir, "download")
			_ = os.WriteFile(p, data, 0600)
			if e := unpackStoreArchive(p, filepath.Join(dir, "out")); e != nil {
				t.Fatal(e)
			}
		})
	}
	bad := append([]byte(nil), gz.Bytes()...)
	bad[len(bad)-8] ^= 1
	dir := t.TempDir()
	p := filepath.Join(dir, "bad")
	_ = os.WriteFile(p, bad, 0600)
	if unpackStoreArchive(p, filepath.Join(dir, "out")) == nil {
		t.Fatal("bad gzip CRC accepted")
	}
	var zipBytes bytes.Buffer
	zw := zip.NewWriter(&zipBytes)
	w, _ := zw.CreateHeader(&zip.FileHeader{Name: "a", Method: zip.Store})
	_, _ = w.Write([]byte("unique bytes to corrupt"))
	_ = zw.Close()
	bad = zipBytes.Bytes()
	at := bytes.Index(bad, []byte("unique bytes"))
	bad[at] ^= 1
	_ = os.WriteFile(p, bad, 0600)
	if unpackStoreArchive(p, filepath.Join(dir, "out2")) == nil {
		t.Fatal("bad ZIP CRC accepted")
	}
}
func TestStoreRejectsArchivePathsLinksAndRawKPKG(t *testing.T) {
	for _, name := range []string{"../outside", "/absolute", "a/../../bad", "C:/path", "a\\bad", "a/./b"} {
		t.Run(name, func(t *testing.T) {
			var b bytes.Buffer
			z := zip.NewWriter(&b)
			w, _ := z.Create(name)
			_, _ = io.WriteString(w, "bad")
			_ = z.Close()
			dir := t.TempDir()
			p := filepath.Join(dir, "pkg")
			_ = os.WriteFile(p, b.Bytes(), 0600)
			if unpackStoreArchive(p, filepath.Join(dir, "out")) == nil {
				t.Fatal("unsafe path accepted")
			}
		})
	}
	var b bytes.Buffer
	z := zip.NewWriter(&b)
	h := &zip.FileHeader{Name: "link"}
	h.SetMode(os.ModeSymlink | 0777)
	w, _ := z.CreateHeader(h)
	_, _ = io.WriteString(w, "/etc/passwd")
	_ = z.Close()
	dir := t.TempDir()
	p := filepath.Join(dir, "pkg")
	_ = os.WriteFile(p, b.Bytes(), 0600)
	if unpackStoreArchive(p, filepath.Join(dir, "out")) == nil {
		t.Fatal("symlink accepted")
	}
	_ = os.WriteFile(p, []byte("KPKG\x03unsupported"), 0600)
	if unpackStoreArchive(p, filepath.Join(dir, "raw")) == nil {
		t.Fatal("raw KPKG accepted")
	}
}
func TestStoreSignedCatalogRejectsTampering(t *testing.T) {
	public, private, _ := ed25519.GenerateKey(rand.Reader)
	data := []byte(`{"schema":"paperos-store-v1","packages":[]}`)
	signature := ed25519.Sign(private, data)
	tampered := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, ".sig") {
			_, _ = io.WriteString(w, base64.StdEncoding.EncodeToString(signature))
			return
		}
		if tampered {
			_, _ = io.WriteString(w, "{}")
		} else {
			_, _ = w.Write(data)
		}
	}))
	defer server.Close()
	s := storeTestService(t)
	src := StoreSource{URL: server.URL + "/catalog.json", PublicKey: base64.StdEncoding.EncodeToString(public)}
	if _, e := s.storeFetchSource(context.Background(), src); e != nil {
		t.Fatal(e)
	}
	tampered = true
	if _, e := s.storeFetchSource(context.Background(), src); e == nil {
		t.Fatal("tampered catalog accepted")
	}
}
func TestStoreDownloadApprovalAtomicUpdateAndData(t *testing.T) {
	installer := "../build/host/paperos"
	if _, e := os.Stat(installer); e != nil {
		t.Fatal("build native host installer first")
	}
	installer, _ = filepath.Abs(installer)
	s := storeTestService(t)
	s.storeInstaller = installer
	stop := storeServePackage(t, s, storeFixture(t, "papp", "1.0"), "1.0", "papp")
	defer stop()
	mustCommand(t, s, "store-download", "key", "test:org.paperos.store-test")
	j := storeWait(t, s)
	if j.Phase != "ready" {
		t.Fatal(j.Message)
	}
	if _, e := os.Stat(filepath.Join(s.apps, "org.paperos.store-test")); !os.IsNotExist(e) {
		t.Fatal("download executed installation without approval")
	}
	if s.command(url.Values{"cmd": {"store-install"}, "id": {j.ID}, "digest": {"stale"}}) == nil {
		t.Fatal("stale approval accepted")
	}
	mustCommand(t, s, "store-install", "id", j.ID, "digest", j.Digest)
	if j = storeWait(t, s); j.Phase != "done" {
		t.Fatal(j.Message)
	}
	data := filepath.Join(s.apps, ".data", "org.paperos.store-test", "save")
	_ = os.MkdirAll(filepath.Dir(data), 0700)
	_ = os.WriteFile(data, []byte("keep me"), 0600)
	stop2 := storeServePackage(t, s, storeFixture(t, "papp", "2.0"), "2.0", "papp")
	defer stop2()
	s.syncStoreInstalledLocked()
	if !s.store.Entries[0].Update {
		t.Fatal("missing update badge")
	}
	mustCommand(t, s, "store-download", "key", "test:org.paperos.store-test")
	j = storeWait(t, s)
	mustCommand(t, s, "store-install", "id", j.ID, "digest", j.Digest)
	if j = storeWait(t, s); j.Phase != "done" {
		t.Fatal(j.Message)
	}
	m, e := readAppManifest(filepath.Join(s.apps, "org.paperos.store-test"))
	if e != nil || m["version"] != "2.0" {
		t.Fatal("new version not installed", e)
	}
	b, _ := os.ReadFile(data)
	if string(b) != "keep me" {
		t.Fatal("application data changed")
	}
	if s.store.Entries[0].Update {
		t.Fatal("update badge remained after install")
	}
	// Lock is the same flock used by foreground native programs.
	lock, _ := os.OpenFile(filepath.Join(s.apps, ".manager.lock"), os.O_RDWR, 0600)
	defer lock.Close()
	_ = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	mustCommand(t, s, "store-download", "key", "test:org.paperos.store-test")
	j = storeWait(t, s)
	mustCommand(t, s, "store-install", "id", j.ID, "digest", j.Digest)
	if j = storeWait(t, s); j.Phase != "error" {
		t.Fatal("updated an active application")
	}
	m, _ = readAppManifest(filepath.Join(s.apps, "org.paperos.store-test"))
	if m["version"] != "2.0" {
		t.Fatal("failed install damaged old version")
	}
}
func TestStoreDigestMismatchDisabledSourceAndRestart(t *testing.T) {
	s := storeTestService(t)
	stop := storeServePackage(t, s, storeFixture(t, "papp", "1.0"), "1.0", "papp")
	defer stop()
	s.store.Entries[0].SHA256 = strings.Repeat("0", 64)
	mustCommand(t, s, "store-download", "key", "test:org.paperos.store-test")
	j := storeWait(t, s)
	if j.Phase != "error" || !strings.Contains(j.Message, "SHA-256") {
		t.Fatal(j)
	}
	s.store.Sources[0].Enabled = false
	if s.command(url.Values{"cmd": {"store-download"}, "key": {"test:org.paperos.store-test"}}) == nil {
		t.Fatal("disabled source still downloaded")
	}
	s.store.Job = &StoreJob{Phase: "installing"}
	_ = s.saveStoreLocked()
	s.loadStore()
	if s.store.Job.Phase != "error" || s.store.Busy {
		t.Fatal("restart resumed unapproved code")
	}
}
func TestStorePluginUpdatePreservesConfigurationAndLock(t *testing.T) {
	s := storeTestService(t)
	reader := filepath.Join(s.apps, "org.paperos.koreader")
	_ = os.MkdirAll(reader, 0700)
	_ = os.WriteFile(filepath.Join(reader, "manifest.conf"), []byte("id=org.paperos.koreader\nname=KOReader\nversion=1\nexec=run.sh\n"), 0600)
	_ = os.WriteFile(filepath.Join(reader, "run.sh"), []byte("#!/bin/sh\n"), 0700)
	dir := t.TempDir()
	p := filepath.Join(dir, "plugin.zip")
	_ = os.WriteFile(p, storeFixture(t, "koplugin", ""), 0600)
	_ = unpackStoreArchive(p, filepath.Join(dir, "content"))
	payload, _, _ := storeFindPayload(filepath.Join(dir, "content"))
	entry := StoreEntry{ID: "koplugin.example", Name: "Example", Version: "1", Kind: "koplugin"}
	if e := s.installStorePlugin(entry, payload); e != nil {
		t.Fatal(e)
	}
	target := s.storePluginDirectory(entry.ID)
	config := filepath.Join(target, "example_configuration.lua")
	_ = os.WriteFile(config, []byte("private configuration"), 0600)
	if e := s.installStorePlugin(entry, payload); e != nil {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(config)
	if string(b) != "private configuration" {
		t.Fatal("plugin config overwritten")
	}
	s.store.Receipts = map[string]StoreReceipt{}
	s.recoverStorePlugins()
	if len(s.store.Receipts) != 1 {
		t.Fatal("plugin receipt not recovered")
	}
	lock, e := s.storeAppLock()
	if e != nil {
		t.Fatal(e)
	}
	if e = s.installStorePlugin(entry, payload); e == nil {
		t.Fatal("active plugin replaced")
	}
	lock.Close()
	receipt := s.store.Receipts[entry.ID]
	s.removeStorePlugin(receipt)
	if _, e = os.Stat(target); !os.IsNotExist(e) {
		t.Fatal("plugin still loadable after removal")
	}
}
func TestStoreVersionAndCatalogCompatibility(t *testing.T) {
	for _, pair := range [][2]string{{"2026.07.1.1", "2026.07.1"}, {"2.0", "1.9"}, {"1.0", "1.0-rc1"}} {
		if storeVersionCompare(pair[0], pair[1]) <= 0 {
			t.Fatal(pair)
		}
	}
	for _, address := range []string{"http://example.com/a", "https://user:password@example.com/a", "file:///tmp/pkg"} {
		if _, e := storeURL(address, false); e == nil {
			t.Fatal("unsafe URL", address)
		}
	}
	for _, body := range []string{`{"manifest_version":2,"packages":{"example":{"name":"Example","artifacts":[{"url":"https://example.org/x.kpkg","version":[1,2,3],"supported_platforms":["kindlepw2"]}]}}}`, `{"schema_version":1,"packages":[{"id":"example","name":"Example","download_url":"https://example.org/a.zip","version":"1.0","platforms":["koreader"]}]}`, `[{"uri":"legacy","name":"Legacy"}]`} {
		entries, e := parseStoreCatalog([]byte(body), StoreSource{ID: "test", Name: "Test", URL: "https://example.org/catalog.json"})
		if e != nil || len(entries) != 1 {
			t.Fatal(e)
		}
		_, _ = json.Marshal(entries)
	}
}

package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type communityTransport func(*http.Request) (*http.Response, error)

func (f communityTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func communityResponse(body string) *http.Response {
	return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}

func TestStoreCommunityRootsAndPinnedTrust(t *testing.T) {
	for _, address := range []string{"https://repo.zen-labs.org/", "https://xzenlabs.github.io/repo/manifest.json", "https://github.com/xZenLabs/repo"} {
		source, err := storeSourceAddress(address, false)
		if err != nil || source.ID != "zenpm" || source.PublicKey != "9Fz6j8YEaqFbRcNDIHSsvkkKHmpmgcVxIDooiMsyNLQ=" {
			t.Fatalf("%s: %+v %v", address, source, err)
		}
	}
	source, err := storeSourceAddress("https://example.org/my-repo/", false)
	if err != nil || source.URL != "https://example.org/my-repo/manifest.json" || source.PublicKey != "" {
		t.Fatal(source, err)
	}
	source, err = storeSourceAddress("https://github.com/example/apps", false)
	if err != nil || source.URL != "https://api.github.com/repos/example/apps/contents/manifest.json" || source.BaseURL != "https://raw.githubusercontent.com/example/apps/HEAD/manifest.json" {
		t.Fatal(source, err)
	}
	source, err = storeSourceAddress("https://repo.zen-labs.org:8443/manifest.json", false)
	if err != nil || source.PublicKey != "" {
		t.Fatal("A different origin inherited a trusted key")
	}
	for _, preset := range storePresets() {
		if preset.PublicKey != "" {
			key, e := base64.StdEncoding.DecodeString(preset.PublicKey)
			if e != nil || len(key) != ed25519.PublicKeySize {
				t.Fatal("Invalid bundled key", preset.ID)
			}
		}
	}
}

func TestStoreZenPMActualMetadataClassifiesPackages(t *testing.T) {
	data, err := os.ReadFile("testdata/store/zenpm.json")
	if err != nil {
		t.Fatal(err)
	}
	source, _ := storePreset("zenpm")
	entries, err := parseStoreCatalog(data, source)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]StoreEntry{}
	for _, entry := range entries {
		seen[entry.ID] = entry
	}
	if e := seen["koplugin.batterygraph"]; e.Kind != "koplugin" || e.Reason != "" || e.VersionsURL != "https://repo.zen-labs.org/packages/koreader/batterygraph.koplugin/versions.json" {
		t.Fatal(e)
	}
	for _, id := range []string{"kopatch.focus-reading-lua", "font.font-cartisse", "iconpack.fluent-icon-pack", "kindle-browser", "zenpm-kobo"} {
		if e := seen[id]; e.ID == "" || e.Reason == "" {
			t.Fatal("Unsupported payload offered as an installable plugin", id, e)
		}
	}
	if e := seen["koplugin.clock"]; e.URL != "https://github.com/jperon/clock.koplugin" || !storeUnresolvedVersion(e.Version) {
		t.Fatal(e)
	}
}

func TestStoreZenPMRawSignatureAndFailedRefreshCache(t *testing.T) {
	pub, key, _ := ed25519.GenerateKey(rand.Reader)
	body := []byte(`{"schema_version":1,"packages":[{"id":"example","name":"Example","version":"1","platforms":["koreader"],"download_url":"plugin.zip"}]}`)
	signature := ed25519.Sign(key, body)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, ".sig") {
			_, _ = w.Write(signature)
		} else {
			_, _ = w.Write(body)
		}
	}))
	defer server.Close()
	s := storeTestService(t)
	source := StoreSource{ID: "test", Name: "Signed", URL: server.URL + "/manifest.json", PublicKey: base64.StdEncoding.EncodeToString(pub), Enabled: true}
	entries, err := s.storeFetchSource(context.Background(), source)
	if err != nil || len(entries) != 1 {
		t.Fatal(err)
	}
	s.store.Sources = []StoreSource{source}
	s.store.Entries = entries
	body = append(body, ' ')
	s.refreshStore()
	if len(s.store.Entries) != 1 || s.store.Entries[0].ID != "koplugin.example" || !strings.Contains(s.store.Sources[0].Error, "签名") {
		t.Fatal("Bad signature discarded the working cache or was accepted")
	}
}

func TestStoreSourceOnlyPluginPinsCommitWhenReleaseListEmpty(t *testing.T) {
	s := storeTestService(t)
	sha := strings.Repeat("a", 40)
	s.storeClient = &http.Client{Transport: communityTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/versions.json" {
			return communityResponse(`{"releases":[]}`), nil
		}
		if strings.HasSuffix(r.URL.Path, "/releases/latest") {
			response := communityResponse("{}")
			response.StatusCode = 404
			return response, nil
		}
		if strings.HasSuffix(r.URL.Path, "/commits") {
			return communityResponse(`[{"sha":"` + sha + `"}]`), nil
		}
		t.Fatalf("Unexpected request %s", r.URL)
		return nil, nil
	})}
	entry, err := s.resolveStoreEntry(context.Background(), StoreEntry{ID: "koplugin.clock", Kind: "koplugin", Version: "source", Homepage: "https://github.com/example/clock.koplugin", VersionsURL: "https://repo.example.org/versions.json"})
	if err != nil || entry.Version != "git:"+sha[:12] || entry.URL != "https://api.github.com/repos/example/clock.koplugin/zipball/"+sha {
		t.Fatal(entry, err)
	}
}

func TestStoreContribUsesPinnedModuleMetadata(t *testing.T) {
	s := storeTestService(t)
	sha := strings.Repeat("b", 40)
	module := strings.Repeat("c", 40)
	s.storeClient = &http.Client{Transport: communityTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.String() != "https://api.github.com/repos/koreader/contrib/git/blobs/"+module {
			t.Fatal("Submodule metadata was not pinned", r.URL)
		}
		content := base64.StdEncoding.EncodeToString([]byte("[submodule \"clock.koplugin\"]\npath = clock.koplugin\nurl = git@github.com:example/clock.koplugin.git\n"))
		return communityResponse(`{"encoding":"base64","content":"` + content + `"}`), nil
	})}
	source, _ := storePreset("koreader-contrib")
	data := []byte(`{"tree":[{"path":".gitmodules","type":"blob","sha":"` + module + `"},{"path":"clock.koplugin","type":"commit","sha":"` + sha + `"},{"path":"../escape.koplugin","type":"commit","sha":"` + sha + `"}]}`)
	entries, err := s.fetchStoreContrib(context.Background(), source, data)
	if err != nil || len(entries) != 1 || entries[0].ID != "koplugin.clock" || entries[0].Version != "git:"+sha[:12] || entries[0].URL != "https://api.github.com/repos/example/clock.koplugin/zipball/"+sha {
		t.Fatal(entries, err)
	}
}

func TestStoreZenPMDownloadInstallAndUpdate(t *testing.T) {
	s := storeTestService(t)
	reader := filepath.Join(s.apps, "org.paperos.koreader")
	_ = os.MkdirAll(reader, 0700)
	_ = os.WriteFile(filepath.Join(reader, "manifest.conf"), []byte("id=org.paperos.koreader\nname=KOReader\nversion=1.0\nexec=run.sh\n"), 0600)
	_ = os.WriteFile(filepath.Join(reader, "run.sh"), []byte("#!/bin/sh\nexit 0\n"), 0700)
	body := storeFixture(t, "koplugin", "")
	digest := sha256.Sum256(body)
	version := "1.0"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/versions.json" {
			fmt.Fprintf(w, `{"releases":[{"tag_name":%q,"assets":[{"name":"example.koplugin.zip","url":"plugin.zip","digest":"sha256:%s","size":%d}]}]}`, version, hex.EncodeToString(digest[:]), len(body))
		} else {
			_, _ = w.Write(body)
		}
	}))
	defer server.Close()
	entry := StoreEntry{Key: "test:koplugin.example", SourceID: "test", ID: "koplugin.example", Kind: "koplugin", Name: "Example", Version: "source", VersionsURL: server.URL + "/versions.json"}
	s.store.Entries = []StoreEntry{entry}
	for _, want := range []string{"1.0", "2.0"} {
		version = want
		mustCommand(t, s, "store-download", "key", entry.Key)
		job := storeWait(t, s)
		if job.Phase != "ready" || !job.Verified || job.Entry.Version != want {
			t.Fatal(job)
		}
		if want == "1.0" {
			if _, err := os.Stat(s.storePluginDirectory(entry.ID)); !os.IsNotExist(err) {
				t.Fatal("Downloaded code installed before local approval")
			}
		}
		mustCommand(t, s, "store-install", "id", job.ID, "digest", job.Digest)
		job = storeWait(t, s)
		if job.Phase != "done" {
			t.Fatal(job)
		}
		s.recoverStorePlugins()
		if receipt := s.store.Receipts[entry.ID]; receipt.Digest != job.Digest || receipt.Key != entry.Key || receipt.Version != want {
			t.Fatal("Plugin provenance did not survive recovery", receipt)
		}
		config := filepath.Join(s.storePluginDirectory(entry.ID), "example_configuration.lua")
		if want == "1.0" {
			_ = os.WriteFile(config, []byte("return {personal=true}"), 0600)
		} else {
			b, _ := os.ReadFile(config)
			if string(b) != "return {personal=true}" {
				t.Fatal("Update replaced user configuration")
			}
		}
	}
}

func TestStorePluginUpdatesRemainBoundToTheirSource(t *testing.T) {
	s := storeTestService(t)
	id := "koplugin.example"
	target := s.storePluginDirectory(id)
	_ = os.MkdirAll(target, 0700)
	_ = os.WriteFile(filepath.Join(target, "main.lua"), []byte("return {}"), 0600)
	s.store.Receipts[id] = StoreReceipt{ID: id, Kind: "koplugin", Key: "test:" + id, Version: "1.0", Directory: target}
	s.store.Entries = []StoreEntry{{ID: id, Key: "test:" + id, Version: "2.0", Kind: "koplugin"}, {ID: id, Key: "other:" + id, Version: "git:aaaaaaaaaaaa", Kind: "koplugin"}}
	s.syncStoreInstalledLocked()
	if !s.store.Entries[0].Update || s.store.Entries[1].Update || s.store.Entries[1].Installed != "" {
		t.Fatal("A different repository changed the app's update source")
	}
}

func TestStoreGitHubReleaseAssetMatchesTagNameAndDigest(t *testing.T) {
	s := storeTestService(t)
	digest := strings.Repeat("d", 64)
	s.storeClient = &http.Client{Transport: communityTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.String() != "https://api.github.com/repos/example/plugin/releases/tags/v1.0" {
			t.Fatal(r.URL)
		}
		return communityResponse(`{"assets":[{"name":"other.zip","url":"https://api.github.com/repos/example/plugin/releases/assets/1"},{"name":"example.koplugin.zip","url":"https://api.github.com/repos/example/plugin/releases/assets/2","digest":"sha256:` + digest + `"}]}`), nil
	})}
	address := "https://github.com/example/plugin/releases/download/v1.0/example.koplugin.zip"
	resolved, err := s.storeAssetURL(context.Background(), address, digest)
	if err != nil || resolved != "https://api.github.com/repos/example/plugin/releases/assets/2" {
		t.Fatal(resolved, err)
	}
	if _, err = s.storeAssetURL(context.Background(), address, strings.Repeat("e", 64)); err == nil {
		t.Fatal("A conflicting publisher digest was ignored")
	}
}

func TestStoreCommunityMetadataMirrorKeepsUpstreamAndLimits(t *testing.T) {
	s := storeTestService(t)
	addresses := []string{}
	s.storeClient = &http.Client{Transport: communityTransport(func(r *http.Request) (*http.Response, error) {
		addresses = append(addresses, r.URL.String())
		if r.URL.Hostname() == "api.github.com" {
			if r.Header.Get("Accept") != "application/vnd.github.raw+json" {
				t.Fatal("Mirror returned base64 metadata")
			}
			return nil, fmt.Errorf("temporary API failure")
		}
		return communityResponse(`{"releases":[]}`), nil
	})}
	address := "https://repo.zen-labs.org/packages/koreader/example.koplugin/versions.json"
	data, err := s.storeFetch(context.Background(), address, 1000)
	if err != nil || string(data) != `{"releases":[]}` || len(addresses) != 2 || addresses[0] != "https://api.github.com/repos/xZenLabs/repo/contents/packages/koreader/example.koplugin/versions.json" || addresses[1] != address {
		t.Fatal(addresses, err)
	}
	for _, untrusted := range []string{"https://other.example/manifest.json", "https://repo.zen-labs.org:8443/manifest.json"} {
		if candidates := storeMetadataAddresses(untrusted); len(candidates) != 1 || candidates[0] != untrusted {
			t.Fatal("An unrelated origin was silently replaced", candidates)
		}
	}
}

// Optional audit of the exact public snapshots fetched during deployment.
func TestStoreFullCommunitySnapshots(t *testing.T) {
	root := os.Getenv("PAPEROS_COMMUNITY_FIXTURES")
	if root == "" {
		t.Skip("Set PAPEROS_COMMUNITY_FIXTURES to a directory of fetched public catalogs")
	}
	for _, item := range []struct{ name, id string }{{"zenpm.json", "zenpm"}, {"kpm.json", "kpm"}} {
		body, err := os.ReadFile(filepath.Join(root, item.name))
		if err != nil {
			t.Fatal(err)
		}
		source, _ := storePreset(item.id)
		entries, err := parseStoreCatalog(body, source)
		if err != nil || len(entries) == 0 {
			t.Fatal(item.name, err)
		}
		t.Log(item.id, "entries", len(entries))
		if item.id == "zenpm" {
			pub, _ := base64.StdEncoding.DecodeString(source.PublicKey)
			signature, err := os.ReadFile(filepath.Join(root, "zenpm-sig.txt"))
			if err != nil || !ed25519.Verify(pub, body, signature) {
				t.Fatal("Live ZenPM snapshot signature failed")
			}
		}
	}
	tree, err := os.ReadFile(filepath.Join(root, "contrib-tree.json"))
	if err != nil {
		t.Fatal(err)
	}
	modules, err := os.ReadFile(filepath.Join(root, "contrib-modules.txt"))
	if err != nil {
		t.Fatal(err)
	}
	s := storeTestService(t)
	s.storeClient = &http.Client{Transport: communityTransport(func(r *http.Request) (*http.Response, error) {
		metadata, _ := json.Marshal(map[string]string{"encoding": "base64", "content": base64.StdEncoding.EncodeToString(modules)})
		return communityResponse(string(metadata)), nil
	})}
	source, _ := storePreset("koreader-contrib")
	entries, err := s.fetchStoreContrib(context.Background(), source, tree)
	if err != nil || len(entries) < 50 {
		t.Fatal("Real KOReader contrib snapshot failed", err)
	}
	t.Log("KOReader contrib entries", len(entries))
}

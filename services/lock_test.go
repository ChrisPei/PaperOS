package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func lockPNG(t *testing.T, gray uint8) []byte {
	t.Helper()
	im := image.NewGray(image.Rect(0, 0, 100, 150))
	for i := range im.Pix {
		im.Pix[i] = gray
	}
	var b bytes.Buffer
	if e := png.Encode(&b, im); e != nil {
		t.Fatal(e)
	}
	return b.Bytes()
}
func lockPhoto(i int) SpotlightImage {
	u := fmt.Sprintf("https://res.public.onecdn.static.microsoft/creativeservice/portrait-%d.jpg", i)
	h := sha256.Sum256([]byte(u))
	return SpotlightImage{ID: hex.EncodeToString(h[:]), URL: u, Title: fmt.Sprintf("Photo %d", i), Copyright: "Example photographer"}
}
func addLockPhoto(t *testing.T, s *Service, i int, now time.Time) {
	t.Helper()
	if e := s.installSpotlight(lockPhoto(i), lockPNG(t, byte(17*i)), now); e != nil {
		t.Fatal(e)
	}
}
func TestIdleLockUsesUptimeAndActivityDoesNotWritePersistentState(t *testing.T) {
	s := testService(t)
	s.cfg.Lock.IdleSeconds = 60
	s.lock.LastActivity = 100
	now := time.Date(2026, 10, 16, 9, 0, 0, 0, china)
	s.tickLock(now.Add(24*time.Hour), 159)
	if s.lock.Locked {
		t.Fatal("a wall clock jump caused early idle lock")
	}
	s.tickLock(now, 160)
	if !s.lock.Locked {
		t.Fatal("idle deadline did not lock")
	}
	mustCommand(t, s, "lock-activity")
	if !s.lock.Locked {
		t.Fatal("touch activity unlocked the device")
	}
	mustCommand(t, s, "lock-unlock")
	if s.lock.Locked {
		t.Fatal("unlock failed")
	}
	if _, e := os.Stat(filepath.Join(s.root, "state.json")); !os.IsNotExist(e) {
		t.Fatal("transient touches rewrote persistent config")
	}
	mustCommand(t, s, "lock-idle", "seconds", "0")
	s.tickLock(now, uptime()+6000)
	if s.lock.Locked {
		t.Fatal("disabled idle lock fired")
	}
	if e := s.command(url.Values{"cmd": {"lock-idle"}, "seconds": {"2"}}); e == nil {
		t.Fatal("invalid idle interval accepted")
	}
}
func TestLockedStateSurvivesBackendRestartWithoutDiscardingReminders(t *testing.T) {
	s := testService(t)
	s.cfg.Lock.IdleSeconds = 300
	mustCommand(t, s, "timer-start", "seconds", "1")
	mustCommand(t, s, "lock-now")
	s.tick(time.Now().Add(2*time.Second), uptime()+2, bootID())
	if s.cfg.Active == nil || !s.lock.Locked {
		t.Fatal("locked timer did not alert")
	}
	mustCommand(t, s, "alert-stop", "id", s.cfg.Active.ID)
	if !s.lock.Locked {
		t.Fatal("stopping a reminder unlocked the underlying app")
	}
	restarted := testService(t)
	restarted.root = s.root
	restarted.run = s.run
	restarted.loadLock()
	if !restarted.lock.Locked {
		t.Fatal("service restart bypassed lock")
	}
}
func TestSpotlightConversionAndMemoryBounds(t *testing.T) {
	b, e := spotlightPGM(lockPNG(t, 102))
	if e != nil {
		t.Fatal(e)
	}
	if !bytes.HasPrefix(b, []byte(lockPGMHeader)) || len(b) != len(lockPGMHeader)+600*800 {
		t.Fatal("wrong panel format")
	}
	for _, v := range b[len(lockPGMHeader):] {
		if v != 102 {
			t.Fatal("gray image changed during crop/dither")
		}
	}
	if _, e = spotlightPGM([]byte("bad jpeg")); e == nil {
		t.Fatal("invalid image accepted")
	}
	var large bytes.Buffer
	// A compact PNG with impossible dimensions must be rejected before Decode.
	im := image.NewGray(image.Rect(0, 0, 9000, 100))
	im.SetGray(1, 1, color.Gray{Y: 100})
	_ = png.Encode(&large, im)
	if _, e = spotlightPGM(large.Bytes()); e == nil {
		t.Fatal("oversized image accepted")
	}
}
func TestSpotlightSevenImageCacheDailySelectionAndCorruptRecovery(t *testing.T) {
	s := testService(t)
	now := time.Now().In(china)
	for i := 1; i <= 9; i++ {
		addLockPhoto(t, s, i, now)
	}
	if len(s.spotlight.Entries) != 7 {
		t.Fatalf("cache contains %d photos", len(s.spotlight.Entries))
	}
	first := s.spotlight.Current
	if first != lockPhoto(1).ID {
		t.Fatal("same-day refresh replaced the selected photo")
	}
	files, _ := filepath.Glob(filepath.Join(s.cacheDir(), "*.pgm"))
	if len(files) != 14 {
		t.Fatal("evicted photo files were retained")
	}
	s.selectPhotoLocked(now.AddDate(0, 0, 1))
	if s.spotlight.Current == first {
		t.Fatal("offline next day did not rotate")
	}
	selected := s.spotlight.Current
	s.selectPhotoLocked(now.AddDate(0, 0, 1).Add(time.Minute))
	if s.spotlight.Current != selected {
		t.Fatal("photograph rotated twice in one local day")
	}
	if e := os.WriteFile(s.photoPath(selected), []byte("damaged"), 0600); e != nil {
		t.Fatal(e)
	}
	restarted := testService(t)
	restarted.root = s.root
	restarted.loadLock()
	if len(restarted.spotlight.Entries) != 6 || restarted.spotlight.Current == selected {
		t.Fatal("corrupt photo did not fall back to an intact cache entry")
	}
}
func spotlightJSON(images ...SpotlightImage) []byte {
	items := []map[string]string{}
	for _, im := range images {
		ad, _ := json.Marshal(map[string]any{"ad": map[string]any{"portraitImage": map[string]string{"asset": im.URL}, "title": im.Title, "copyright": im.Copyright}, "tracking": map[string]string{"baseUri": "https://tracking.invalid/never-contact"}})
		items = append(items, map[string]string{"item": string(ad)})
	}
	b, _ := json.Marshal(map[string]any{"batchrsp": map[string]any{"items": items}})
	return b
}

type spotlightTransport func(*http.Request) (*http.Response, error)

func (f spotlightTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestRealSpotlightResponsePrefillsSevenAndFailureKeepsCache(t *testing.T) {
	s := testService(t)
	queries, downloads := 0, 0
	s.httpClient = &http.Client{Transport: spotlightTransport(func(r *http.Request) (*http.Response, error) {
		var data []byte
		if r.URL.Host == "fd.api.iris.microsoft.com" {
			queries++
			start := 1
			if r.URL.Query().Get("country") != "CN" {
				start = 5
			}
			data = spotlightJSON(lockPhoto(start), lockPhoto(start+1), lockPhoto(start+2), lockPhoto(start+3))
		} else if r.URL.Host == "res.public.onecdn.static.microsoft" {
			downloads++
			data = lockPNG(t, byte(downloads*17))
		} else {
			t.Fatalf("unexpected network/tracking host %s", r.URL.Host)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(data)), Header: make(http.Header)}, nil
	})}
	s.refreshSpotlight()
	if queries != 2 || downloads != 8 || len(s.spotlight.Entries) != 7 || s.spotlightBusy {
		t.Fatalf("failed prefill: queries=%d downloads=%d cache=%d", queries, downloads, len(s.spotlight.Entries))
	}
	selected := s.spotlight.Current
	s.httpClient = &http.Client{Transport: spotlightTransport(func(r *http.Request) (*http.Response, error) { return nil, fmt.Errorf("offline") })}
	s.refreshSpotlight()
	if len(s.spotlight.Entries) != 7 || s.spotlight.Current != selected {
		t.Fatal("network outage discarded offline images")
	}
	if !strings.Contains(s.spotlightMessage, "保留") {
		t.Fatal("outage status missing")
	}
}
func TestSpotlightRejectsOtherSourcesAndTraversal(t *testing.T) {
	for _, address := range []string{"http://res.public.onecdn.static.microsoft/a.jpg", "https://localhost/a.jpg", "https://res.public.onecdn.static.microsoft.evil/a.jpg", "https://user@res.public.onecdn.static.microsoft/a.jpg", "https://res.public.onecdn.static.microsoft:123/a.jpg"} {
		u, _ := url.Parse(address)
		if spotlightURLAllowed(u) {
			t.Fatalf("unsafe source %s accepted", address)
		}
	}
	if _, e := parseSpotlight(spotlightJSON(SpotlightImage{URL: "file:///etc/passwd"})); e == nil {
		t.Fatal("local asset accepted")
	}
	if validPhotoID("../state") {
		t.Fatal("path traversal accepted")
	}
}

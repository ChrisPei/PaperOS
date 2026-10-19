package main

import (
	"archive/tar"
	"bytes"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testService(t *testing.T) *Service {
	t.Helper()
	dir := t.TempDir()
	s := &Service{root: filepath.Join(dir, "data"), run: filepath.Join(dir, "run"), packages: filepath.Join(dir, "packages"), apps: filepath.Join(dir, "apps"), simulate: true, transfers: map[string]*Transfer{}, httpClient: &http.Client{Timeout: time.Second}}
	for _, p := range []string{s.root, s.run, s.packages, s.apps} {
		if e := os.MkdirAll(p, 0700); e != nil {
			t.Fatal(e)
		}
	}
	return s
}
func mustCommand(t *testing.T, s *Service, cmd string, pairs ...string) {
	t.Helper()
	v := url.Values{"cmd": {cmd}}
	for i := 0; i < len(pairs); i += 2 {
		v.Set(pairs[i], pairs[i+1])
	}
	if e := s.command(v); e != nil {
		t.Fatal(e)
	}
}
func TestTimerUsesBootClockAndSurvivesServiceRestart(t *testing.T) {
	s := testService(t)
	now := time.Date(2026, 10, 16, 9, 0, 0, 0, china)
	s.cfg.Timer = newTimer(25, now, 100, "same-boot")
	s.tick(now.Add(12*time.Hour), 110, "same-boot")
	if s.cfg.Active != nil {
		t.Fatal("wall-clock adjustment fired a relative timer")
	}
	data, e := json.Marshal(s.cfg)
	if e != nil {
		t.Fatal(e)
	}
	restarted := testService(t)
	if e = json.Unmarshal(data, &restarted.cfg); e != nil {
		t.Fatal(e)
	}
	restarted.tick(now.Add(-time.Hour), 125, "same-boot")
	if restarted.cfg.Active == nil || restarted.cfg.Active.Kind != "timer" {
		t.Fatal("timer did not survive service restart")
	}
	restarted.tick(now, 130, "same-boot")
	if len(restarted.cfg.Queue) != 0 {
		t.Fatal("timer fired twice")
	}
}
func TestTimerRebootFallbackAndPause(t *testing.T) {
	now := time.Date(2026, 10, 16, 9, 0, 0, 0, china)
	timer := newTimer(60, now, 100, "old")
	if n := timerRemaining(&timer, now.Add(20*time.Second), 5, "new"); n != 40 {
		t.Fatalf("reboot remaining %d", n)
	}
	if n := timerRemaining(&timer, now.Add(-time.Hour), 15, "new"); n != 30 {
		t.Fatalf("wall correction changed rebased timer %d", n)
	}
	s := testService(t)
	mustCommand(t, s, "timer-start", "seconds", "60")
	mustCommand(t, s, "timer-pause")
	if s.cfg.Timer.State != "paused" || s.cfg.Timer.Remaining < 58 {
		t.Fatal("pause lost remaining time")
	}
	mustCommand(t, s, "timer-resume")
	mustCommand(t, s, "timer-cancel")
	if s.cfg.Timer.State != "" {
		t.Fatal("cancel did not clear timer")
	}
}
func TestRecurringAlarmTimezoneAndQueuedReminders(t *testing.T) {
	s := testService(t)
	friday := time.Date(2026, 10, 16, 8, 42, 0, 0, china)
	a := Alarm{ID: 1, Hour: 7, Minute: 30, Days: 31, Enabled: true, Label: "起床"}
	if got := time.Unix(nextAlarm(a, friday), 0).In(china); got.Weekday() != time.Monday || got.Hour() != 7 {
		t.Fatal(got)
	}
	a.Next = friday.Unix()
	s.cfg.Alarms = []Alarm{a}
	s.cfg.Timer = newTimer(1, friday, 10, "boot")
	s.tick(friday.Add(time.Second), 11, "boot")
	if s.cfg.Active == nil || len(s.cfg.Queue) != 1 {
		t.Fatal("simultaneous reminders were lost")
	}
	id := s.cfg.Active.ID
	if e := s.command(url.Values{"cmd": {"alert-stop"}, "id": {"stale"}}); e == nil {
		t.Fatal("stale acknowledgement accepted")
	}
	mustCommand(t, s, "alert-stop", "id", id)
	if s.cfg.Active == nil || s.cfg.Active.Kind != "timer" {
		t.Fatal("next reminder not shown")
	}
	mustCommand(t, s, "alert-snooze", "id", s.cfg.Active.ID)
	if s.cfg.Active != nil || s.cfg.Snooze.State != "running" {
		t.Fatal("snooze did not persist")
	}
}
func TestAlarmValidationAndNoHostTimeChanges(t *testing.T) {
	s := testService(t)
	for _, v := range []url.Values{
		{"cmd": {"alarm-save"}, "hour": {"24"}, "minute": {"0"}, "days": {"0"}},
		{"cmd": {"timer-start"}, "seconds": {"0"}},
		{"cmd": {"time-set"}, "value": {"2026-10-16 12:00"}},
	} {
		if e := s.command(v); e == nil {
			t.Fatal("invalid or simulated operation accepted")
		}
	}
	mustCommand(t, s, "alarm-save", "hour", "7", "minute", "30", "days", "31", "label", "起床")
	mustCommand(t, s, "alarm-toggle", "id", "1")
	if s.cfg.Alarms[0].Enabled {
		t.Fatal("toggle failed")
	}
	mustCommand(t, s, "alarm-remove", "id", "1")
	if len(s.cfg.Alarms) != 0 {
		t.Fatal("remove failed")
	}
}
func TestScanPreservesUnicodeAndMarksEnterpriseNetworks(t *testing.T) {
	rows := parseScan("bssid / frequency / signal level / flags / ssid\n00:11\t2412\t-40\t[WPA2-PSK-CCMP]\t家里\n00:12\t2412\t-42\t[WPA2-PSK-CCMP]\t家里\n00:13\t2412\t-52\t[WPA2-EAP]\tOffice\n00:14\t2412\t-70\t[ESS]\tGuest\\x20WiFi\n")
	if len(rows) != 3 || rows[0].SSID != "家里" || rows[1].Security != "企业认证" || rows[2].SSID != "Guest WiFi" {
		t.Fatalf("%+v", rows)
	}
	if decoded, _ := hex.DecodeString(rows[0].Hex); string(decoded) != "家里" {
		t.Fatal("SSID bytes changed")
	}
}
func bundle(t *testing.T, entries map[string]string) []byte {
	t.Helper()
	var b bytes.Buffer
	writer := tar.NewWriter(&b)
	for name, value := range entries {
		if e := writer.WriteHeader(&tar.Header{Name: name, Size: int64(len(value)), Mode: 0755, Typeflag: tar.TypeReg}); e != nil {
			t.Fatal(e)
		}
		if _, e := writer.Write([]byte(value)); e != nil {
			t.Fatal(e)
		}
	}
	if e := writer.Close(); e != nil {
		t.Fatal(e)
	}
	return b.Bytes()
}
func validBundle(t *testing.T) []byte {
	return bundle(t, map[string]string{
		"package/manifest.conf": "id=org.test.app\nname=测试应用\nversion=1.0\nexec=run.sh\nwidget=clock\n",
		"package/run.sh":        "#!/bin/sh\nexit 0\n",
	})
}
func TestPackageUnpackerRejectsTraversalLinksAndInvalidMetadata(t *testing.T) {
	good := validBundle(t)
	if m, e := unpackPackage(bytes.NewReader(good), t.TempDir()); e != nil || m["name"] != "测试应用" {
		t.Fatal(m, e)
	}
	for _, name := range []string{"../outside", "package/../../outside", "/package/evil", "package/a\\b", "package/./a"} {
		if _, e := unpackPackage(bytes.NewReader(bundle(t, map[string]string{name: "oops"})), t.TempDir()); e == nil {
			t.Fatalf("accepted %q", name)
		}
	}
	var b bytes.Buffer
	w := tar.NewWriter(&b)
	_ = w.WriteHeader(&tar.Header{Name: "package/run.sh", Typeflag: tar.TypeSymlink, Linkname: "/etc/passwd"})
	_ = w.Close()
	if _, e := unpackPackage(&b, t.TempDir()); e == nil {
		t.Fatal("symlink accepted")
	}
}
func TestPhysicalConfirmationBindsCertificateBundleAndNonce(t *testing.T) {
	a := confirmationCode([]byte("certificate"), strings.Repeat("0", 64), strings.Repeat("1", 32))
	if len(a) != 6 || a != confirmationCode([]byte("certificate"), strings.Repeat("0", 64), strings.Repeat("1", 32)) {
		t.Fatal("unstable code")
	}
	if a == confirmationCode([]byte("attacker certificate"), strings.Repeat("0", 64), strings.Repeat("1", 32)) {
		t.Fatal("code not bound to TLS certificate")
	}
}
func TestTLSUploadRequiresPhysicalApprovalAndNeverExecutesPackage(t *testing.T) {
	s := testService(t)
	s.cfg.WiFi = true
	s.net.Connected = true
	s.receiveUntil = time.Now().Add(time.Minute)
	pair, e := s.ensureCertificate()
	if e != nil {
		t.Fatal(e)
	}
	server := httptest.NewUnstartedServer(http.HandlerFunc(s.transferHandler))
	server.TLS = &tls.Config{Certificates: []tls.Certificate{pair}, MinVersion: tls.VersionTLS12}
	server.StartTLS()
	defer server.Close()
	data := validBundle(t)
	sum := sha256.Sum256(data)
	request, e := http.NewRequest("POST", server.URL+"/upload", bytes.NewReader(data))
	if e != nil {
		t.Fatal(e)
	}
	request.Header.Set("X-PaperOS-Nonce", strings.Repeat("c", 32))
	request.Header.Set("X-PaperOS-SHA256", fmt.Sprintf("%x", sum))
	response, e := server.Client().Do(request)
	if e != nil {
		t.Fatal(e)
	}
	raw, _ := io.ReadAll(response.Body)
	response.Body.Close()
	if response.StatusCode != 202 || !strings.Contains(string(raw), "pending") {
		t.Fatal(response.StatusCode, string(raw))
	}
	if s.pending == nil || s.pending.Code != confirmationCode(server.Certificate().Raw, fmt.Sprintf("%x", sum), strings.Repeat("c", 32)) {
		t.Fatal("TLS/code binding changed")
	}
}
func TestWeatherParsingAndCacheSurvivesProviderFailure(t *testing.T) {
	s := testService(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("timezone") != "Asia/Shanghai" || r.URL.Query().Get("timeformat") != "unixtime" {
			t.Error("weather query lost timezone or epoch time")
		}
		times := []int64{}
		values := []float64{}
		for i := 0; i < 72; i++ {
			times = append(times, 1760000400+int64(i)*3600)
			values = append(values, 16)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"current": map[string]any{"temperature_2m": 16, "weather_code": 3}, "daily": map[string]any{"temperature_2m_max": []float64{20}, "temperature_2m_min": []float64{11}}, "hourly": map[string]any{"time": times, "temperature_2m": values, "weather_code": values, "precipitation_probability": values, "wind_speed_10m": values}})
	}))
	defer server.Close()
	s.weatherURL = server.URL
	s.httpClient = server.Client()
	w, e := s.fetchWeather()
	if e != nil || len(w.Hours) != 72 || w.Temperature != 16 {
		t.Fatal(w, e)
	}
	s.cfg.Weather = w
	s.cfg.Weather.Fetched = 1
	s.net.Connected = true
	server.Close()
	s.refreshWeather()
	if len(s.cfg.Weather.Hours) != 72 || !strings.Contains(s.cfg.Weather.Message, "缓存") {
		t.Fatal("offline cache was lost")
	}
}

// Exercise the exact HTTP upload flow, including pending/reject transitions.
func TestUploadHTTPStateMachine(t *testing.T) {
	s := testService(t)
	s.cfg.WiFi = true
	s.net.Connected = true
	s.receiveUntil = time.Now().Add(time.Minute)
	s.certificate = []byte("test certificate")
	data := validBundle(t)
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	nonce := strings.Repeat("1", 32)
	request := httptest.NewRequest("POST", "https://paperos/upload", bytes.NewReader(data))
	request.Header.Set("X-PaperOS-Nonce", nonce)
	request.Header.Set("X-PaperOS-SHA256", digest)
	response := httptest.NewRecorder()
	s.transferHandler(response, request)
	if response.Code != 202 {
		t.Fatal(response.Code, response.Body.String())
	}
	p := s.pending
	if p == nil || p.Phase != "pending" {
		t.Fatal("no pending request")
	}
	if _, e := os.Stat(filepath.Join(s.packages, "org.test.app.papp")); !os.IsNotExist(e) {
		t.Fatal("package admitted before confirmation")
	}
	if p.Code != confirmationCode(s.certificate, digest, nonce) {
		t.Fatal("wrong displayed code")
	}
	mustCommand(t, s, "receive-approve", "id", p.ID)
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		phase := p.Phase
		s.mu.Unlock()
		if phase == "received" {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if _, e := os.Stat(filepath.Join(s.packages, "org.test.app.papp/run.sh")); e != nil {
		t.Fatal(e)
	}
	// Approval admits the bundle to the library; it does not run arbitrary code.
	if _, e := os.Stat(filepath.Join(s.apps, "org.test.app")); !os.IsNotExist(e) {
		t.Fatal("package automatically installed")
	}
}
func TestRejectedUploadNeverEntersLibrary(t *testing.T) {
	s := testService(t)
	s.cfg.WiFi = true
	s.net.Connected = true
	s.receiveUntil = time.Now().Add(time.Minute)
	s.certificate = []byte("cert")
	data := validBundle(t)
	sum := sha256.Sum256(data)
	r := httptest.NewRequest("POST", "https://paperos/upload", bytes.NewReader(data))
	r.Header.Set("X-PaperOS-Nonce", strings.Repeat("a", 32))
	r.Header.Set("X-PaperOS-SHA256", fmt.Sprintf("%x", sum))
	w := httptest.NewRecorder()
	s.transferHandler(w, r)
	if w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	p := s.pending
	mustCommand(t, s, "receive-reject", "id", p.ID)
	if p.Phase != "rejected" || s.pending != nil {
		t.Fatal("reject failed")
	}
	if _, e := os.Stat(filepath.Join(s.packages, "org.test.app.papp")); !os.IsNotExist(e) {
		t.Fatal("rejected package admitted")
	}
}

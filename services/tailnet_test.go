package main

import (
	"bytes"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func localTailnetAPI(t *testing.T, status int, body string) string {
	t.Helper()
	socket := filepath.Join(t.TempDir(), "ts.sock")
	listener, e := net.Listen("unix", socket)
	if e != nil {
		t.Fatal(e)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/localapi/v0/status" || r.URL.Query().Get("peers") != "false" || r.Host != "local-tailscaled.sock" {
			t.Error("unexpected LocalAPI request", r.Host, r.URL)
		}
		w.WriteHeader(status)
		_, _ = io.WriteString(w, body)
	})}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() { _ = server.Close() })
	return socket
}

func TestTailnetStatusReadsOnlyLocalNodeAndFailsClosed(t *testing.T) {
	body := `{"Version":"1.104.1","BackendState":"Running","Self":{"HostName":"paperos-test","Online":true,"TailscaleIPs":["fd7a:115c:a1e0::1","100.101.102.103"]},"User":{"private-account":"DO_NOT_EXPORT"},"AuthURL":"DO_NOT_EXPORT"}`
	state, e := readTailnetStatus(localTailnetAPI(t, 200, body))
	if e != nil || !state.Connected || state.Name != "paperos-test" || state.IP != "100.101.102.103" {
		t.Fatal(state, e)
	}
	encoded, _ := json.Marshal(state)
	if bytes.Contains(encoded, []byte("DO_NOT_EXPORT")) {
		t.Fatal("private daemon metadata exported")
	}
	for _, test := range []struct {
		status int
		body   string
	}{{503, body}, {200, "{"}, {200, strings.Repeat(" ", 1024*1024+1)}} {
		got, e := readTailnetStatus(localTailnetAPI(t, test.status, test.body))
		if e == nil || got.Connected {
			t.Fatal("unavailable status did not fail closed", got, e)
		}
	}
	state, e = readTailnetStatus(localTailnetAPI(t, 200, strings.Replace(body, "Running", "NeedsLogin", 1)))
	if e != nil || state.Connected || state.Message != "需要在电脑完成授权" {
		t.Fatal(state, e)
	}
}

func tailnetService(t *testing.T) *Service {
	s := testService(t)
	s.cfg.WiFi = true
	s.net.Connected = true
	s.net.IP = "127.0.0.2"
	s.cfg.Tailnet = TailnetConfig{Version: 1, Enabled: true, AllowReceive: true}
	s.tailnet = TailnetState{Installed: true, Connected: true, IP: "100.101.102.103", Name: "paperos-test"}
	s.receiveUntil = time.Now().Add(time.Minute)
	t.Cleanup(func() {
		s.mu.Lock()
		defer s.mu.Unlock()
		if s.receiver != nil {
			_ = s.receiver.Close()
		}
		if s.receiverTailnet != nil {
			_ = s.receiverTailnet.Close()
		}
	})
	return s
}

func receiverClient(t *testing.T, s *Service) *http.Client {
	t.Helper()
	certificate, e := x509.ParseCertificate(s.certificate)
	if e != nil {
		t.Fatal(e)
	}
	pool := x509.NewCertPool()
	pool.AddCert(certificate)
	transport := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: pool, ServerName: "paperos.local", MinVersion: tls.VersionTLS12}}
	t.Cleanup(transport.CloseIdleConnections)
	return &http.Client{Transport: transport, Timeout: 2 * time.Second}
}

func TestTailnetReceiverWindowSwitchesAndWifiAddressChange(t *testing.T) {
	s := tailnetService(t)
	s.reconcileReceiver()
	if s.receiver == nil || s.receiverTailnet == nil {
		t.Fatal("both listeners required", s.message)
	}
	client := receiverClient(t, s)
	check := func(ip string) []byte {
		t.Helper()
		r, e := client.Get("https://" + ip + ":8765/status")
		if e != nil {
			t.Fatal(ip, e)
		}
		defer r.Body.Close()
		if r.StatusCode != 404 {
			t.Fatal("unexpected response", ip, r.StatusCode)
		}
		return r.TLS.PeerCertificates[0].Raw
	}
	if !bytes.Equal(check("127.0.0.2"), check("127.0.0.1")) {
		t.Fatal("certificate differs between paths")
	}
	remote := s.receiverTailnet
	s.mu.Lock()
	s.net.IP = "127.0.0.3"
	s.mu.Unlock()
	s.reconcileReceiver()
	check("127.0.0.3")
	check("127.0.0.1")
	if s.receiverTailnet != remote {
		t.Fatal("Wi-Fi address change replaced stable tailnet listener")
	}
	if r, e := client.Get("https://127.0.0.2:8765/status"); e == nil {
		r.Body.Close()
		t.Fatal("old Wi-Fi listener remains")
	}
	s.mu.Lock()
	s.cfg.Tailnet.AllowReceive = false
	s.mu.Unlock()
	s.reconcileReceiver()
	check("127.0.0.3")
	if s.receiverTailnet != nil {
		t.Fatal("remote receiver did not close")
	}
	if r, e := client.Get("https://127.0.0.1:8765/status"); e == nil {
		r.Body.Close()
		t.Fatal("remote port remains reachable")
	}
	s.mu.Lock()
	s.cfg.Tailnet.AllowReceive = true
	s.receiveUntil = time.Now().Add(-time.Second)
	s.mu.Unlock()
	s.reconcileReceiver()
	if s.receiver != nil || s.receiverTailnet != nil {
		t.Fatal("receiver window did not close both paths")
	}
}

func TestTailnetUploadRequiresApprovalAndClosingRemoteRejectsPending(t *testing.T) {
	s := tailnetService(t)
	s.reconcileReceiver()
	client := receiverClient(t, s)
	data := validBundle(t)
	digest := sha256.Sum256(data)
	hexDigest := hex.EncodeToString(digest[:])
	nonce := strings.Repeat("a", 32)
	upload := func() {
		t.Helper()
		request, e := http.NewRequest("POST", "https://127.0.0.1:8765/upload", bytes.NewReader(data))
		if e != nil {
			t.Fatal(e)
		}
		request.Header.Set("X-PaperOS-SHA256", hexDigest)
		request.Header.Set("X-PaperOS-Nonce", nonce)
		r, e := client.Do(request)
		if e != nil {
			t.Fatal(e)
		}
		defer r.Body.Close()
		if r.StatusCode != 202 {
			body, _ := io.ReadAll(r.Body)
			t.Fatal(r.StatusCode, string(body))
		}
	}
	upload()
	s.mu.Lock()
	pending := s.pending
	s.mu.Unlock()
	if pending == nil || !pending.ViaTailnet || pending.Peer != "Tailscale 私网" || pending.Code != confirmationCode(s.certificate, hexDigest, nonce) {
		t.Fatal("wrong confirmation binding", pending)
	}
	if _, e := os.Stat(filepath.Join(s.packages, pending.AppID+".papp")); !os.IsNotExist(e) {
		t.Fatal("unapproved package published", e)
	}
	if e := s.command(url.Values{"cmd": {"tailnet-receive"}, "enabled": {"false"}}); e != nil {
		t.Fatal(e)
	}
	s.mu.Lock()
	rejected := s.pending == nil && pending.Phase == "rejected"
	s.mu.Unlock()
	if !rejected {
		t.Fatal("remote switch left approval actionable")
	}
	s.reconcileReceiver()
	if e := s.command(url.Values{"cmd": {"receive-approve"}, "id": {pending.ID}}); e == nil {
		t.Fatal("rejected request could be approved")
	}
	s.mu.Lock()
	s.cfg.Tailnet.AllowReceive = true
	s.mu.Unlock()
	s.reconcileReceiver()
	nonce = strings.Repeat("b", 32)
	upload()
	s.mu.Lock()
	pending = s.pending
	s.mu.Unlock()
	if e := s.command(url.Values{"cmd": {"receive-approve"}, "id": {pending.ID}}); e != nil {
		t.Fatal(e)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		phase := pending.Phase
		s.mu.Unlock()
		if phase == "received" {
			if _, e := os.Stat(filepath.Join(s.packages, pending.AppID+".papp", "manifest.conf")); e != nil {
				t.Fatal(e)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("approved transfer did not complete")
}

func TestTailnetRemoteHandlerGatesEveryPermission(t *testing.T) {
	for _, test := range []struct {
		name    string
		disable func(*Service)
	}{
		{"master off", func(s *Service) { s.cfg.Tailnet.Enabled = false }},
		{"remote off", func(s *Service) { s.cfg.Tailnet.AllowReceive = false }},
		{"tailnet offline", func(s *Service) { s.tailnet.Connected = false }},
		{"Wi-Fi off", func(s *Service) { s.cfg.WiFi = false }},
		{"disconnected", func(s *Service) { s.net.Connected = false }},
		{"airplane", func(s *Service) { s.cfg.Airplane = true }},
		{"window expired", func(s *Service) { s.receiveUntil = time.Now().Add(-time.Second) }},
	} {
		t.Run(test.name, func(t *testing.T) {
			s := tailnetService(t)
			test.disable(s)
			s.mu.Lock()
			allowed := s.transferAllowedLocked(true)
			s.mu.Unlock()
			if allowed {
				t.Fatal("remote path remains allowed")
			}
		})
	}
}

func TestTailnetTogglePersistsWithoutResettingIdentityOrHomeCredentials(t *testing.T) {
	s := tailnetService(t)
	marker := filepath.Join(t.TempDir(), "enabled")
	identity := filepath.Join(s.root, "identity")
	home := filepath.Join(s.root, "mihome.json")
	for _, path := range []string{identity, home} {
		if e := os.WriteFile(path, []byte("preserve-existing-identity-and-scope"), 0600); e != nil {
			t.Fatal(e)
		}
	}
	s.tailnetSwitch = func(on bool) error { return setTailnetMarker(marker, on) }
	s.tailnetReader = func() (TailnetState, error) {
		return TailnetState{Installed: true, Connected: true, Name: "paperos-test", IP: "100.101.102.103"}, nil
	}
	for _, on := range []bool{false, true} {
		if e := s.command(url.Values{"cmd": {"tailnet-enable"}, "enabled": {fmt.Sprint(on)}}); e != nil {
			t.Fatal(e)
		}
		deadline := time.Now().Add(time.Second)
		done := false
		for time.Now().Before(deadline) {
			s.mu.Lock()
			busy := s.tailnet.Busy
			s.mu.Unlock()
			if !busy {
				done = true
				break
			}
			time.Sleep(5 * time.Millisecond)
		}
		if !done {
			t.Fatal("tailnet toggle did not complete")
		}
		var cfg Config
		data, e := os.ReadFile(filepath.Join(s.root, "state.json"))
		if e != nil || json.Unmarshal(data, &cfg) != nil || cfg.Tailnet.Enabled != on {
			t.Fatal("configuration not persisted", e)
		}
		_, e = os.Stat(marker)
		if (e == nil) != on {
			t.Fatal("startup marker did not follow toggle", on, e)
		}
	}
	for _, path := range []string{identity, home} {
		data, e := os.ReadFile(path)
		if e != nil || string(data) != "preserve-existing-identity-and-scope" {
			t.Fatal("identity or NAS credentials changed", e)
		}
	}
}

func TestDeviceTailnetLocalAPI(t *testing.T) {
	if os.Getenv("PAPEROS_TEST_REAL_TAILNET") != "1" {
		t.Skip("physical-device LocalAPI test not requested")
	}
	state, e := readTailnetStatus(tailnetSocket)
	if e != nil || !state.Connected || !isTailnetIPv4(state.IP) {
		t.Fatal(state, e)
	}
	t.Logf("TAILNET_LOCAL_API connected=%t name=%s ip=%s version=%s", state.Connected, state.Name, state.IP, state.Version)
}

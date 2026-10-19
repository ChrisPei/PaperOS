package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func homeTestConfig(server string) MiHomeConfig {
	return MiHomeConfig{Version: 1, BaseURL: server, Token: "test-only-secret", Name: "测试家庭", Items: []MiHomeBinding{{Entity: "sensor.room_temperature", Label: "温度", Room: "客厅", Kind: "temperature"}}}
}
func TestMiHomeValidatesScopeAndLocalProxy(t *testing.T) {
	c := homeTestConfig("http://127.0.0.1:8123")
	if validateMiHome(&c) != nil {
		t.Fatal("valid config rejected")
	}
	c.Proxy = "socks5://127.0.0.1:1055"
	if validateMiHome(&c) != nil {
		t.Fatal("loopback SOCKS transport rejected")
	}
	for _, change := range []func(*MiHomeConfig){func(c *MiHomeConfig) { c.BaseURL = "file:///etc/passwd" }, func(c *MiHomeConfig) { c.Proxy = "http://example.com:1234" }, func(c *MiHomeConfig) { c.Proxy = "socks5://example.com:1234" }, func(c *MiHomeConfig) { c.Items[0].Entity = "sensor.x/../../actions" }, func(c *MiHomeConfig) { c.Token = "secret\r\nheader" }, func(c *MiHomeConfig) { c.Items = append(c.Items, c.Items[0]) }} {
		c := homeTestConfig("http://127.0.0.1:8123")
		change(&c)
		if validateMiHome(&c) == nil {
			t.Fatal("unsafe config accepted")
		}
	}
}
func TestMiHomeReadsOnlySelectedStateAndKeepsUnits(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/api/states/sensor.room_temperature" || r.Header.Get("Authorization") != "Bearer test-only-secret" {
			t.Error("unselected action or wrong authentication")
		}
		fmt.Fprint(w, `{"entity_id":"sensor.room_temperature","state":"23.6","attributes":{"unit_of_measurement":"°C"}}`)
	}))
	defer server.Close()
	c := homeTestConfig(server.URL)
	item, e := fetchMiHomeValue(context.Background(), miHomeClient(c), c, c.Items[0])
	if e != nil || !item.Available || item.Value != "23.6" || item.Unit != "°C" {
		t.Fatal("valid reading lost", item, e)
	}
}

func TestMiHomeHTTPProxyTunnelsWithoutForwardedHeadersOrProxyCredentials(t *testing.T) {
	home := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Forwarded-For") != "" || r.Header.Get("Authorization") != "Bearer test-only-secret" || r.URL.Path != "/api/states/sensor.room_temperature" {
			t.Error("HA request was changed by the proxy")
		}
		fmt.Fprint(w, `{"entity_id":"sensor.room_temperature","state":"23.6","attributes":{"unit_of_measurement":"°C"}}`)
	}))
	defer home.Close()
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodConnect || r.Header.Get("Authorization") != "" || r.Host != strings.TrimPrefix(home.URL, "http://") {
			t.Error("CONNECT leaked credentials or used the wrong target")
			w.WriteHeader(400)
			return
		}
		upstream, e := net.Dial("tcp", r.Host)
		if e != nil {
			t.Error(e)
			w.WriteHeader(502)
			return
		}
		conn, buffered, e := w.(http.Hijacker).Hijack()
		if e != nil {
			upstream.Close()
			t.Error(e)
			return
		}
		defer conn.Close()
		defer upstream.Close()
		buffered.WriteString("HTTP/1.1 200 Connection Established\r\n\r\n")
		buffered.Flush()
		go func() { io.Copy(upstream, buffered.Reader); upstream.Close() }()
		io.Copy(conn, upstream)
	}))
	defer proxy.Close()
	c := homeTestConfig(home.URL)
	c.Proxy = proxy.URL
	client := miHomeClient(c)
	defer client.CloseIdleConnections()
	item, e := fetchMiHomeValue(context.Background(), client, c, c.Items[0])
	if e != nil || !item.Available || item.Value != "23.6" {
		t.Fatal("transparent proxy read failed", item, e)
	}
}
func TestMiHomeUnavailableAndInvalidNumericAreNotFakeReadings(t *testing.T) {
	for _, value := range []string{"unavailable", "unknown", "NaN", "Infinity"} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprintf(w, `{"entity_id":"sensor.room_temperature","state":%q}`, value)
		}))
		c := homeTestConfig(server.URL)
		item, e := fetchMiHomeValue(context.Background(), miHomeClient(c), c, c.Items[0])
		server.Close()
		if e != nil || item.Available {
			t.Fatal("missing value shown as live", value, item, e)
		}
	}
}
func TestMiHomeNeverFollowsRedirectWithBearerToken(t *testing.T) {
	called := false
	destination := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true }))
	defer destination.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, destination.URL, 302) }))
	defer server.Close()
	c := homeTestConfig(server.URL)
	_, e := fetchMiHomeValue(context.Background(), miHomeClient(c), c, c.Items[0])
	if e == nil || called {
		t.Fatal("authorization followed redirect")
	}
}
func waitHome(t *testing.T, s *Service) {
	t.Helper()
	for i := 0; i < 300; i++ {
		s.mu.Lock()
		busy := s.mihome.Busy
		s.mu.Unlock()
		if !busy {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("home update did not finish")
}
func TestMiHomeCachesReadingsButNeverPublishesCredentials(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"entity_id":"sensor.room_temperature","state":"23.6","attributes":{"unit_of_measurement":"°C"}}`)
	}))
	defer server.Close()
	s := testService(t)
	s.net.Connected = true
	s.mihome.Config = homeTestConfig(server.URL)
	s.mihome.Configured = true
	s.pollMiHome(true)
	waitHome(t, s)
	s.publish()
	if s.mihome.Cache.At == 0 || len(s.mihome.Cache.Items) != 1 {
		t.Fatal("real reading not cached")
	}
	for _, name := range []string{"state.tsv", "mihome.tsv"} {
		data, e := os.ReadFile(filepath.Join(s.run, name))
		if e != nil || strings.Contains(string(data), s.mihome.Config.Token) {
			t.Fatal("credential in public snapshot", name, e)
		}
	}
	data, e := os.ReadFile(filepath.Join(s.root, "mihome-cache.json"))
	if e != nil || strings.Contains(string(data), s.mihome.Config.Token) {
		t.Fatal("credential in display cache", e)
	}
}
func TestMiHomeOfflineRetainsOldReadingAndTimestamp(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
	defer server.Close()
	s := testService(t)
	s.net.Connected = true
	s.mihome.Config = homeTestConfig(server.URL)
	s.mihome.Configured = true
	s.mihome.Cache = MiHomeCache{At: 123, Items: []MiHomeValue{{Entity: "sensor.room_temperature", Value: "21.0", Available: true, At: 123}}}
	s.pollMiHome(true)
	waitHome(t, s)
	if s.mihome.Cache.At != 123 || s.mihome.Cache.Items[0].Value != "21.0" || !s.mihome.Cache.Items[0].Stale {
		t.Fatal("offline cache relabeled as fresh")
	}
}
func TestMiHomeRefreshTokenUpdatesPrivateCredentials(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/auth/token" {
			_ = r.ParseForm()
			if r.Method != "POST" || r.Form.Get("refresh_token") != "private-refresh" {
				t.Error("wrong refresh request")
			}
			fmt.Fprint(w, `{"access_token":"new-test-token","expires_in":1800}`)
			return
		}
		if r.Method != "GET" || r.Header.Get("Authorization") != "Bearer new-test-token" {
			t.Error("unexpected control operation or token")
		}
		fmt.Fprint(w, `{"entity_id":"sensor.room_temperature","state":"22.4"}`)
	}))
	defer server.Close()
	s := testService(t)
	s.net.Connected = true
	c := homeTestConfig(server.URL)
	c.RefreshToken = "private-refresh"
	c.ClientID = "http://localhost:12345/"
	s.mihome.Config = c
	s.mihome.Configured = true
	s.pollMiHome(true)
	waitHome(t, s)
	data, e := os.ReadFile(filepath.Join(s.root, "mihome.json"))
	var saved MiHomeConfig
	if e != nil || json.Unmarshal(data, &saved) != nil || saved.Token != "new-test-token" || saved.RefreshToken != c.RefreshToken {
		t.Fatal("token refresh not preserved", e)
	}
	info, e := os.Stat(filepath.Join(s.root, "mihome.json"))
	if e != nil || info.Mode().Perm() != 0600 {
		t.Fatal("credentials readable by other users")
	}
}
func TestMiHomeUninstalledApplicationDoesNotPoll(t *testing.T) {
	s := testService(t)
	s.simulate = false
	s.net.Connected = true
	s.mihome.Config = homeTestConfig("http://127.0.0.1:1")
	s.mihome.Configured = true
	s.pollMiHome(true)
	if s.mihome.Busy || s.mihome.Run != 0 {
		t.Fatal("removed application kept querying the home")
	}
}

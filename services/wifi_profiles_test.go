package main

import (
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeWiFiProfile struct {
	ssid     string
	enabled  bool
	priority string
}
type fakeWiFi struct {
	mu                         sync.Mutex
	rows                       map[int]*fakeWiFiProfile
	current, next, adds, saves int
	refuseAuth                 bool
	persisted                  map[int]fakeWiFiProfile
}

func newFakeWiFi(t *testing.T) (*Service, *fakeWiFi) {
	t.Helper()
	s := testService(t)
	s.simulate = false
	s.cfg.WiFi = true
	f := &fakeWiFi{rows: map[int]*fakeWiFiProfile{0: {"Home", true, "10"}, 1: {"Office", false, "0"}}, current: 0, next: 2}
	s.wifiControl = f.control
	s.wifiAddress = func() string { return "192.168.5.8" }
	s.networkWait = func(time.Duration) {}
	s.dhcpRunner = func() error { return nil }
	return s, f
}
func (f *fakeWiFi) control(args ...string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	switch args[0] {
	case "list_networks":
		var out strings.Builder
		out.WriteString("network id / ssid / bssid / flags\n")
		ids := []int{}
		for id := range f.rows {
			ids = append(ids, id)
		}
		sort.Ints(ids)
		for _, id := range ids {
			p := f.rows[id]
			flags := ""
			if !p.enabled {
				flags = "[DISABLED]"
			}
			if id == f.current {
				flags = "[CURRENT]"
			}
			fmt.Fprintf(&out, "%d\t%s\tany\t%s\n", id, p.ssid, flags)
		}
		return out.String(), nil
	case "status":
		if p, okay := f.rows[f.current]; okay {
			return fmt.Sprintf("wpa_state=COMPLETED\nid=%d\nssid=%s\n", f.current, p.ssid), nil
		}
		return "wpa_state=DISCONNECTED\n", nil
	case "add_network":
		id := f.next
		f.next++
		f.adds++
		f.rows[id] = &fakeWiFiProfile{enabled: false}
		return strconv.Itoa(id), nil
	case "set_network":
		id, _ := strconv.Atoi(args[1])
		p, okay := f.rows[id]
		if !okay {
			return "", errors.New("missing")
		}
		if args[2] == "ssid" {
			raw, _ := hex.DecodeString(args[3])
			p.ssid = string(raw)
		}
		if args[2] == "priority" {
			p.priority = args[3]
		}
		return "OK", nil
	case "select_network":
		id, _ := strconv.Atoi(args[1])
		for key, p := range f.rows {
			p.enabled = key == id
		}
		if !f.refuseAuth {
			f.current = id
		}
		return "OK", nil
	case "enable_network":
		for _, p := range f.rows {
			p.enabled = true
		}
		return "OK", nil
	case "remove_network":
		id, _ := strconv.Atoi(args[1])
		delete(f.rows, id)
		if f.current == id {
			f.current = -1
		}
		return "OK", nil
	case "save_config":
		f.saves++
		f.persisted = map[int]fakeWiFiProfile{}
		for id, p := range f.rows {
			f.persisted[id] = *p
		}
		return "OK", nil
	case "reassociate", "ping":
		return "OK", nil
	}
	return "", fmt.Errorf("unhandled control %s", args[0])
}
func wifiHex(value string) string { return hex.EncodeToString([]byte(value)) }
func TestSavedWiFiReconnectDoesNotCreateOrRequestCredentials(t *testing.T) {
	s, f := newFakeWiFi(t)
	s.connectNetwork(wifiHex("Office"), "", true)
	if f.adds != 0 || f.current != 1 || f.saves != 1 {
		t.Fatalf("reuse failed: adds=%d current=%d saves=%d", f.adds, f.current, f.saves)
	}
	if len(f.persisted) != 2 {
		t.Fatal("another saved network was lost")
	}
	for _, p := range f.persisted {
		if !p.enabled {
			t.Fatal("saved fallback remains disabled")
		}
	}
	if f.persisted[1].priority != "10" || f.persisted[0].priority != "0" {
		t.Fatal("selected network is not preferred")
	}
}
func TestNewWiFiKeepsOtherSavedNetworks(t *testing.T) {
	s, f := newFakeWiFi(t)
	s.connectNetwork(wifiHex("Cafe"), "test-password", false)
	if f.adds != 1 || len(f.persisted) != 3 || f.current != 2 {
		t.Fatal("new network replaced an existing one")
	}
	for _, p := range f.persisted {
		if !p.enabled {
			t.Fatal("saved profile was disabled")
		}
	}
}
func TestChangingPasswordPrunesDuplicatesOnlyAfterAuthentication(t *testing.T) {
	s, f := newFakeWiFi(t)
	s.connectNetwork(wifiHex("Home"), "replacement-password", false)
	if len(f.persisted) != 2 || f.rows[0] != nil || f.rows[1] == nil || f.rows[2] == nil {
		t.Fatal("successful credential update did not preserve other profiles")
	}
}
func TestFailedWiFiSwitchPreservesOldProfileAndFallback(t *testing.T) {
	s, f := newFakeWiFi(t)
	f.refuseAuth = true
	s.connectNetwork(wifiHex("Home"), "wrong-password", false)
	if f.saves != 0 || len(f.rows) != 2 || f.rows[0] == nil || f.rows[1] == nil {
		t.Fatal("failed connection damaged saved profiles")
	}
	for _, p := range f.rows {
		if !p.enabled {
			t.Fatal("failed selection left a profile disabled")
		}
	}
}
func TestStartupRecoversDisabledProfilesAndPrunesCurrentDuplicates(t *testing.T) {
	s, f := newFakeWiFi(t)
	f.rows[2] = &fakeWiFiProfile{ssid: "Home", enabled: false}
	if e := s.restoreSavedNetworks(); e != nil {
		t.Fatal(e)
	}
	if len(f.persisted) != 2 || !f.persisted[1].enabled || f.rows[2] != nil {
		t.Fatal("legacy profiles were not repaired")
	}
}
func TestForgetWiFiRemovesOnlySelectedSSID(t *testing.T) {
	s, f := newFakeWiFi(t)
	f.rows[2] = &fakeWiFiProfile{ssid: "Office"}
	s.forgetNetwork(wifiHex("Office"))
	if len(f.persisted) != 1 || f.rows[0] == nil || !f.rows[0].enabled {
		t.Fatal("forget affected another network")
	}
}
func TestWiFiProfilesDecodeNamesAndExcludeCredentials(t *testing.T) {
	rows := parseSavedWiFi("0\tGuest\\x20WiFi\tany\t[DISABLED]\n1\t家里\tany\t[CURRENT]\ninvalid\tbad\tany\t\n")
	if len(rows) != 2 || rows[0].SSID != "Guest WiFi" || !rows[1].Current || rows[1].Hex != wifiHex("家里") {
		t.Fatalf("wrong profiles: %+v", rows)
	}
	if parseWPAStatus("ssid=Guest\\x20WiFi\n")["ssid"] != "Guest WiFi" {
		t.Fatal("status SSID cannot match a saved profile")
	}
}
func TestAutomaticSavedWiFiRoamRenewsDHCP(t *testing.T) {
	s, f := newFakeWiFi(t)
	f.current = 1
	s.net.LeaseSSID = "Home"
	leases := make(chan struct{}, 4)
	s.dhcpRunner = func() error { leases <- struct{}{}; return nil }
	s.pollNetwork()
	select {
	case <-leases:
	case <-time.After(time.Second):
		t.Fatal("roaming kept the previous network's lease")
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		done := s.net.LeaseSSID == "Office" && !s.net.LeaseBusy
		s.mu.Unlock()
		if done {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("new saved network did not finish reconnecting")
}

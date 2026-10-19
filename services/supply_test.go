package main

import (
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestExternalPowerIncludesChargerFullBatteryAndUnreadableCapacity(t *testing.T) {
	for _, c := range []struct {
		name, ac, usb, status string
		powered, known        bool
	}{
		{"charger only", "1", "0", "Charging", true, true},
		{"full on charger", "1", "0", "Full", true, true},
		{"USB power without data", "0", "1", "Full", true, true},
		{"charging fallback", "", "", "Charging", true, true},
		{"battery", "0", "0", "Discharging", false, true},
		{"full but unplugged", "0", "0", "Full", false, true},
		{"missing sensor", "0", "", "Full", false, false},
		{"invalid sensor", "maybe", "0", "Discharging", false, false},
	} {
		t.Run(c.name, func(t *testing.T) {
			powered, e := externalPowerReading(func(path string) string {
				switch path {
				case "/sys/class/power_supply/bd7181x_ac/online":
					return c.ac
				case "/sys/class/power_supply/imx6_usb_charger/online":
					return c.usb
				case "/sys/class/power_supply/bd7181x_bat/status":
					return c.status
				default:
					t.Fatal("power policy must not depend on capacity or USB data", path)
					return ""
				}
			})
			if powered != c.powered || (e == nil) != c.known {
				t.Fatalf("powered=%v, err=%v", powered, e)
			}
		})
	}
}

func TestPoweredIdleDeadlineAndUnplugRestoreBaseSetting(t *testing.T) {
	s := testService(t)
	s.cfg.Lock.IdleSeconds = 60
	s.cfg.Lock.PoweredMultiplier = 3
	s.supply = ExternalPowerState{Known: true}
	powered := true
	s.supplyReader = func() (bool, error) { return powered, nil }
	s.refreshExternalPowerLocked(100)
	now := time.Now()
	s.tickLock(now, 279)
	if s.lock.Locked {
		t.Fatal("powered device locked before the multiplied deadline")
	}
	s.tickLock(now, 280)
	if !s.lock.Locked {
		t.Fatal("powered idle deadline never locked")
	}
	// A supply change must not undo a deliberate or timed lock.
	powered = false
	s.refreshExternalPowerLocked(300)
	if !s.lock.Locked || s.cfg.Lock.IdleSeconds != 60 || s.effectiveIdleLocked() != 60 {
		t.Fatal("unplug overwrote the base setting or unlocked the screen")
	}
	s.lock.Locked = false
	s.tickLock(now, 359)
	if s.lock.Locked {
		t.Fatal("unplug did not restart the ordinary idle period")
	}
	s.tickLock(now, 360)
	if !s.lock.Locked {
		t.Fatal("ordinary idle lock was not restored on battery")
	}
	s.lock.Locked = false
	s.cfg.Lock.IdleSeconds = 0
	powered = true
	s.refreshExternalPowerLocked(400)
	s.tickLock(now, 100000)
	if s.lock.Locked {
		t.Fatal("power multiplier enabled disabled auto lock")
	}
}

func TestPoweredMultiplierMigratesAndPersistsWithoutChangingBaseTimeout(t *testing.T) {
	s := testService(t)
	s.cfg.Lock.IdleSeconds = 300
	s.loadLock()
	if s.cfg.Lock.PoweredMultiplier != 5 {
		t.Fatal("old configuration did not acquire default 5x policy")
	}
	mustCommand(t, s, "lock-powered-multiplier", "times", "3")
	data, e := os.ReadFile(filepath.Join(s.root, "state.json"))
	var saved Config
	if e != nil || json.Unmarshal(data, &saved) != nil || saved.Lock.PoweredMultiplier != 3 || saved.Lock.IdleSeconds != 300 {
		t.Fatal("policy was not persisted independently of base timeout")
	}
	for _, value := range []string{"0", "1", "4", "999999999999", ""} {
		if e := s.command(url.Values{"cmd": {"lock-powered-multiplier"}, "times": {value}}); e == nil {
			t.Fatal("invalid multiplier accepted", value)
		}
	}
	if s.cfg.Lock.PoweredMultiplier != 3 {
		t.Fatal("rejected command changed policy")
	}
	// A failed write cannot leave a setting that only looks persisted.
	s.root = filepath.Join(s.root, "state.json", "not-a-directory")
	if e := s.command(url.Values{"cmd": {"lock-powered-multiplier"}, "times": {"10"}}); e == nil || s.cfg.Lock.PoweredMultiplier != 3 {
		t.Fatal("failed persistence changed active multiplier")
	}
}

func TestExternalPowerBlocksAutomaticAndManualSleepWithoutLocking(t *testing.T) {
	s := sleepService(t)
	s.supplyReader = func() (bool, error) { return true, nil }
	s.sleep.Requested = true
	s.refreshExternalPowerLocked(uptime())
	if reason := s.sleepBlockLocked(time.Now(), uptime()); !strings.Contains(reason, "外接电源") {
		t.Fatal("manual intent overrode external power", reason)
	}
	s.lock.Locked = false
	if e := s.command(url.Values{"cmd": {"sleep-now"}}); e == nil || !strings.Contains(e.Error(), "外接电源") || s.lock.Locked || s.sleep.Requested {
		t.Fatal("powered manual sleep was not rejected before locking", e)
	}
	s.supplyReader = func() (bool, error) { return false, errors.New("sensor read failed") }
	s.refreshExternalPowerLocked(uptime())
	if s.supply.Known || s.powerSleepBlockLocked() == "" {
		t.Fatal("unknown supply allowed hardware suspend")
	}
	s.supplyReader = func() (bool, error) { return false, nil }
	beforeUnplug := uptime()
	mustCommand(t, s, "sleep-now")
	if !s.lock.Locked || !s.sleep.Requested || !s.cfg.Sleep.Enabled || s.lock.LastActivity < beforeUnplug {
		t.Fatal("manual sleep did not recover after unplug")
	}
}

func TestPlugDuringSleepPreparationCancelsBeforeHardwareWithoutFailure(t *testing.T) {
	s := sleepService(t)
	s.sleep.Busy = true
	var powered atomic.Bool
	s.supplyReader = func() (bool, error) { return powered.Load(), nil }
	called := false
	s.sleepRunner = func(uint64, int64) (SleepResult, error) { called = true; return SleepResult{}, nil }
	// Hold the network handoff until preparation and its display ack have
	// completed, then plug in before the worker is allowed to start.
	ack := []byte("ready 7 3 " + strconv.FormatFloat(uptime(), 'f', 3, 64) + " 123\n")
	if e := os.WriteFile(filepath.Join(s.run, "sleep-display.state"), ack, 0600); e != nil {
		t.Fatal(e)
	}
	s.networkMu.Lock()
	done := make(chan struct{})
	go func() { s.performSleep(7, 3, time.Now().Unix()+30); close(done) }()
	deadline := time.Now().Add(3 * time.Second)
	for {
		if _, e := os.Stat(s.sleepMarkerPath()); e == nil {
			break
		}
		if time.Now().After(deadline) {
			s.networkMu.Unlock()
			<-done
			t.Fatal("sleep preparation did not reach the handoff")
		}
		time.Sleep(10 * time.Millisecond)
	}
	powered.Store(true)
	s.networkMu.Unlock()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("plugging in failed to cancel preparation")
	}
	if called || s.sleep.Busy || s.sleep.Failures != 0 || !s.cfg.Sleep.Enabled || s.sleep.LastSeconds != 0 || !strings.Contains(s.sleep.Message, "外接电源") {
		t.Fatal("cancelled powered handoff executed hardware or recorded a failure")
	}
	var marker SleepMarker
	data, e := os.ReadFile(s.sleepMarkerPath())
	if e != nil || json.Unmarshal(data, &marker) != nil || !marker.Complete {
		t.Fatal("cancelled preparation left an incomplete restart marker")
	}
}

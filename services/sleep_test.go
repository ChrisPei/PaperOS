package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func sleepService(t *testing.T) *Service {
	s := testService(t)
	s.cfg.Sleep = SleepConfig{Version: 1, Enabled: true, USBKeepAwake: true}
	s.sleep = SleepState{Available: true, Cycle: 7, LockGeneration: 3, LockedSince: uptime() - 30}
	s.lock = LockState{Locked: true, Generation: 3}
	s.refreshExternalPower()
	if e := os.WriteFile(filepath.Join(s.run, "sleep-request"), []byte("7\n"), 0600); e != nil {
		t.Fatal(e)
	}
	return s
}
func TestSleepPlansEarliestReminderWithBoottimeTimer(t *testing.T) {
	s := sleepService(t)
	now := time.Now()
	boot := uptime()
	s.cfg.Alarms = []Alarm{{Enabled: true, Next: now.Unix() + 500}}
	s.cfg.Timer = newTimer(80, now, boot, bootID())
	s.cfg.Timer.WallDeadline = now.Unix() + 50000
	if next := s.nextSleepWakeLocked(now, boot); next != now.Unix()+78 {
		t.Fatal("timer wake used a stale wall deadline", next)
	}
	s.cfg.Snooze = newTimer(30, now, boot, bootID())
	if next := s.nextSleepWakeLocked(now, boot); next != now.Unix()+28 {
		t.Fatal("snooze was not the earliest wake", next)
	}
	s.cfg.Timer.State = "paused"
	s.cfg.Snooze.State = "paused"
	if next := s.nextSleepWakeLocked(now, boot); next != now.Unix()+498 {
		t.Fatal("paused timers scheduled a wake", next)
	}
	s.cfg.Alarms = nil
	if next := s.nextSleepWakeLocked(now, boot); next != now.Unix()+1800 {
		t.Fatal("background refresh interval changed")
	}
}
func TestSleepInhibitsUSBReceptionAndNearDueReminders(t *testing.T) {
	now := time.Now()
	boot := uptime()
	for _, scenario := range []struct {
		name  string
		apply func(*Service)
	}{
		{"usb", func(s *Service) { s.sleep.USB = true }},
		{"transfer", func(s *Service) { s.uploading = true }},
		{"receiving", func(s *Service) { s.receiveUntil = now.Add(time.Minute) }},
		{"alert", func(s *Service) { s.cfg.Active = &Alert{ID: "due"} }},
		{"network", func(s *Service) { s.net.Busy = true }},
		{"clock", func(s *Service) { s.clockBusy = true }},
		{"near alarm", func(s *Service) { s.cfg.Alarms = []Alarm{{Enabled: true, Next: now.Unix() + 7}} }},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			s := sleepService(t)
			scenario.apply(s)
			if s.sleepBlockLocked(now, boot) == "" {
				t.Fatal("active operation was not protected")
			}
		})
	}
	s := sleepService(t)
	s.sleep.USB = true
	s.sleep.Requested = true
	if s.sleepBlockLocked(now, boot) != "" {
		t.Fatal("manual request did not override USB stay-awake")
	}
}
func TestUnfinishedSleepMarkerDisablesAutomaticRetryAfterRestart(t *testing.T) {
	s := testService(t)
	data, _ := json.Marshal(SleepMarker{Cycle: 2, BootID: "old", Complete: false})
	if e := os.WriteFile(s.sleepMarkerPath(), data, 0600); e != nil {
		t.Fatal(e)
	}
	s.loadSleep()
	if s.cfg.Sleep.Enabled || !s.cfg.Sleep.USBKeepAwake || !strings.Contains(s.sleep.Message, "未完成") {
		t.Fatal("unfinished sleep can cause a reboot loop")
	}
	var saved Config
	data, e := os.ReadFile(filepath.Join(s.root, "state.json"))
	if e != nil {
		t.Fatal(e)
	}
	if json.Unmarshal(data, &saved) != nil || saved.Sleep.Enabled {
		t.Fatal("retry protection was not persisted")
	}
}
func TestSleepRequiresFreshDisplayAckForSameCycleAndLock(t *testing.T) {
	s := sleepService(t)
	path := filepath.Join(s.run, "sleep-display.state")
	for _, record := range []string{fmt.Sprintf("ready 7 2 %.0f 123\n", uptime()), fmt.Sprintf("ready 6 3 %.0f 123\n", uptime()), fmt.Sprintf("ready 7 3 %.0f 123\n", uptime()-30)} {
		_ = os.WriteFile(path, []byte(record), 0600)
		if s.sleepReady(7, 3) {
			t.Fatal("stale display acknowledgement was accepted")
		}
	}
	_ = os.WriteFile(path, []byte(fmt.Sprintf("ready 7 3 %.0f 123\n", uptime())), 0600)
	if !s.sleepReady(7, 3) {
		t.Fatal("current completed display was not accepted")
	}
}
func TestSleepResultPersistsAndSuccessfulCycleRestoresScheduler(t *testing.T) {
	s := sleepService(t)
	s.sleep.Busy = true
	_ = os.WriteFile(filepath.Join(s.run, "sleep-display.state"), []byte(fmt.Sprintf("ready 7 3 %.0f 123\n", uptime())), 0600)
	s.sleepRunner = func(cycle uint64, deadline int64) (SleepResult, error) {
		if cycle != 7 {
			t.Error("wrong cycle")
		}
		return SleepResult{SuspendedSeconds: 11, WakeReason: "rtc", RTCBefore: 0, RTCAfter: 1}, nil
	}
	s.performSleep(7, 3, time.Now().Unix()+30)
	if s.sleep.Busy || s.sleep.LastSeconds != 11 || s.sleep.LastWake != "rtc" || s.sleep.AwakeUntil <= uptime() {
		t.Fatal("resume state was not recovered")
	}
	data, e := os.ReadFile(s.sleepMarkerPath())
	if e != nil {
		t.Fatal(e)
	}
	var marker SleepMarker
	if json.Unmarshal(data, &marker) != nil || !marker.Complete || marker.Result.SuspendedSeconds != 11 {
		t.Fatal("cycle completion was not persisted")
	}
}
func TestUnlockCancelsBeforeAnyHardwareCall(t *testing.T) {
	s := sleepService(t)
	s.lock.Locked = false
	s.sleep.Busy = true
	called := false
	s.sleepRunner = func(uint64, int64) (SleepResult, error) { called = true; return SleepResult{}, nil }
	s.performSleep(7, 3, time.Now().Unix()+30)
	if called || s.sleep.Busy || s.sleep.Failures != 0 || s.sleep.Phase != "awake" {
		t.Fatal("unlocked display entered hardware suspend")
	}
}
func TestRepeatedSleepFailuresPauseAutomaticSleep(t *testing.T) {
	s := sleepService(t)
	s.sleepRunner = func(uint64, int64) (SleepResult, error) { return SleepResult{}, errors.New("driver failure") }
	for i := 0; i < 3; i++ {
		s.sleep.Busy = true
		_ = os.WriteFile(filepath.Join(s.run, "sleep-request"), []byte("7\n"), 0600)
		_ = os.WriteFile(filepath.Join(s.run, "sleep-display.state"), []byte(fmt.Sprintf("ready 7 3 %.0f 123\n", uptime())), 0600)
		s.performSleep(7, 3, time.Now().Unix()+30)
	}
	if s.cfg.Sleep.Enabled || s.sleep.Failures != 3 {
		t.Fatal("continuous failures were retried indefinitely")
	}
}
func TestResumeRefreshesDueWeatherWithoutWaitingForAwakeTicker(t *testing.T) {
	s := sleepService(t)
	s.sleep.Busy = true
	s.net.Connected = true
	requested := make(chan struct{}, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requested <- struct{}{}
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer server.Close()
	s.weatherURL = server.URL
	s.sleepRunner = func(uint64, int64) (SleepResult, error) {
		return SleepResult{SuspendedSeconds: 11, WakeReason: "rtc"}, nil
	}
	_ = os.WriteFile(filepath.Join(s.run, "sleep-display.state"), []byte(fmt.Sprintf("ready 7 3 %.0f 123\n", uptime())), 0600)
	s.performSleep(7, 3, time.Now().Unix()+30)
	select {
	case <-requested:
	case <-time.After(3 * time.Second):
		t.Fatal("due weather was not requested after resume")
	}
	waitLocation(t, s, func() bool { return !s.weatherBusy && s.cfg.Weather.Message != "" })
}

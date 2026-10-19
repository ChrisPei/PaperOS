package main

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

func ntpReply(request []byte, received, sent time.Time) []byte {
	reply := make([]byte, 48)
	reply[0], reply[1] = 4<<3|4, 2
	copy(reply[24:32], request[40:48])
	putNTPTimestamp(reply[32:], received)
	putNTPTimestamp(reply[40:], sent)
	return reply
}

func TestNTPValidatesRepliesAndResolvesEra(t *testing.T) {
	for _, year := range []int{2026, 2037} {
		at := time.Date(year, 10, 16, 3, 0, 0, 0, china)
		request := make([]byte, 48)
		putNTPTimestamp(request[40:], at.Add(-time.Hour))
		reply := ntpReply(request, at, at.Add(20*time.Millisecond))
		got, err := decodeNTP(reply, request, 100*time.Millisecond)
		if err != nil || got.Sub(at.Add(60*time.Millisecond)) > time.Microsecond || got.Sub(at.Add(60*time.Millisecond)) < -time.Microsecond {
			t.Fatal(got, err)
		}
		for _, mutate := range []func([]byte){
			func(p []byte) { p[0] |= 3 << 6 },
			func(p []byte) { p[1] = 0 },
			func(p []byte) { p[1] = 16 },
			func(p []byte) { p[0] = 4<<3 | 3 },
			func(p []byte) { p[24] ^= 1 },
			func(p []byte) { clear(p[40:48]) },
			func(p []byte) { putNTPTimestamp(p[32:], at.Add(time.Second)) },
		} {
			bad := append([]byte(nil), reply...)
			mutate(bad)
			if _, err := decodeNTP(bad, request, 100*time.Millisecond); err == nil {
				t.Fatal("accepted invalid NTP reply")
			}
		}
		if _, err := decodeNTP(reply[:40], request, time.Second); err == nil {
			t.Fatal("accepted short packet")
		}
	}
}

func TestNTPUsesUDPAndHonorsCancellation(t *testing.T) {
	server, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	done := make(chan struct{})
	at := time.Now()
	go func() {
		defer close(done)
		request := make([]byte, 48)
		_, peer, err := server.ReadFrom(request)
		if err == nil {
			_, _ = server.WriteTo(ntpReply(request, at, at), peer)
		}
	}()
	sample, err := queryNTP(context.Background(), server.LocalAddr().String())
	<-done
	if err != nil || sample.At.Sub(at) < 0 || sample.At.Sub(at) > time.Second {
		t.Fatal(sample, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = queryNTP(ctx, server.LocalAddr().String()); err == nil {
		t.Fatal("cancelled query continued")
	}
}

func waitClock(t *testing.T, s *Service) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		busy := s.clockBusy
		s.mu.Unlock()
		if !busy {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("clock worker did not finish")
}

func mockClock(t *testing.T) (*Service, *atomic.Int32) {
	t.Helper()
	s := testService(t)
	s.simulate = false
	s.cfg.WiFi, s.net.Connected = true, true
	s.cfg.Clock.Automatic = true
	writes := new(atomic.Int32)
	s.clockSetter = func(time.Time) error { writes.Add(1); return nil }
	s.clockRTC = func() error { return nil }
	return s, writes
}

func TestAutomaticTimePreservesCountdownAndRebasesAlarm(t *testing.T) {
	s, writes := mockClock(t)
	now := time.Now()
	s.cfg.Timer = newTimer(120, now, uptime(), bootID())
	deadline := s.cfg.Timer.BootDeadline
	s.cfg.Alarms = []Alarm{{ID: 1, Hour: 7, Minute: 30, Days: 127, Enabled: true}}
	at := now.Add(2 * time.Hour)
	s.clockQuery = func(context.Context) (ClockSample, error) {
		return ClockSample{At: at, Measured: time.Now(), Source: "local-test"}, nil
	}
	s.pollClock()
	waitClock(t, s)
	s.mu.Lock()
	if writes.Load() != 1 || s.cfg.Timer.BootDeadline != deadline || s.cfg.Clock.LastSync < at.Unix() || s.cfg.Alarms[0].Next != nextAlarm(s.cfg.Alarms[0], at) {
		t.Fatal("sync changed a relative timer or failed to rebase the alarm")
	}
	if s.cfg.Timer.WallDeadline < at.Unix()+118 || s.clockNext.Sub(time.Now()) < 5*time.Hour {
		t.Fatal("deadline persistence or polling interval failed")
	}
	s.mu.Unlock()
	s.pollClock()
	if writes.Load() != 1 {
		t.Fatal("automatic sync repeated without waiting")
	}
	var restored Config
	data, _ := os.ReadFile(filepath.Join(s.root, "state.json"))
	if json.Unmarshal(data, &restored) != nil || !restored.Clock.Automatic || restored.Clock.Source != "local-test" {
		t.Fatal("sync preferences or result were not saved")
	}
}

func TestDisablingAutomaticTimeCancelsAnInflightResult(t *testing.T) {
	s, writes := mockClock(t)
	entered, release, returned := make(chan struct{}), make(chan struct{}), make(chan struct{})
	s.clockQuery = func(context.Context) (ClockSample, error) {
		close(entered)
		<-release
		defer close(returned)
		return ClockSample{At: time.Now(), Measured: time.Now()}, nil
	}
	s.pollClock()
	<-entered
	mustCommand(t, s, "time-auto", "enabled", "false")
	close(release)
	<-returned
	time.Sleep(20 * time.Millisecond)
	s.mu.Lock()
	defer s.mu.Unlock()
	if writes.Load() != 0 || s.cfg.Clock.Automatic || s.clockBusy {
		t.Fatal("disabled synchronization still changed the clock")
	}
}

func TestTimeSyncFailureAndOfflineGuardNeverChangeClock(t *testing.T) {
	s, writes := mockClock(t)
	s.cfg.Clock.LastSync, s.cfg.Clock.Source = 1792000000, "previous"
	s.clockQuery = func(context.Context) (ClockSample, error) {
		return ClockSample{}, errors.New("test network failure")
	}
	mustCommand(t, s, "time-sync")
	waitClock(t, s)
	s.mu.Lock()
	if writes.Load() != 0 || s.cfg.Clock.LastSync != 1792000000 || s.clockMessage != "test network failure" || s.clockNext.Sub(time.Now()) > 6*time.Minute {
		t.Fatal("failed sync changed the saved time or did not back off")
	}
	s.net.Connected = false
	s.mu.Unlock()
	if err := s.command(url.Values{"cmd": {"time-sync"}}); err == nil || writes.Load() != 0 {
		t.Fatal("offline sync was accepted")
	}
	simulated := testService(t)
	simulated.cfg.WiFi, simulated.net.Connected = true, true
	if err := simulated.command(url.Values{"cmd": {"time-sync"}}); err == nil {
		t.Fatal("simulation may change the host clock")
	}
}

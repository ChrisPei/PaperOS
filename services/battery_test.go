package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func batteryPoint(at int64, boot, active float64, percent int, powered bool) BatterySample {
	return BatterySample{At: at, BootID: "same-boot", Boot: boot, Active: active, Percent: percent, Powered: powered, Status: "Discharging"}
}
func TestBatterySeparatesObservedSleepAndCharging(t *testing.T) {
	points := []BatterySample{batteryPoint(1000, 100, 50, 80, false), batteryPoint(1600, 700, 70, 79, false), batteryPoint(2200, 1300, 670, 90, true), batteryPoint(2800, 1900, 1270, 95, true)}
	sum := batteryTotals(points, nil, 1000, 2801)
	if sum.Drop != 1 || sum.Observed != 1800 || sum.Sleeping != 580 || sum.EndPercent != 95 {
		t.Fatalf("wrong power accounting: %+v", sum)
	}
}
func TestBatteryRejectsRebootsGapsAndWallClockCorrections(t *testing.T) {
	a := batteryPoint(1000, 100, 50, 80, false)
	for _, b := range []BatterySample{batteryPoint(5000, 4100, 100, 20, false), batteryPoint(1000, 110, 60, 79, false), batteryPoint(5000, 120, 60, 79, false), batteryPoint(1010, 90, 40, 79, false)} {
		if _, _, valid := batteryInterval(a, b); valid {
			t.Fatal("invalid interval connected", b)
		}
	}
	b := batteryPoint(1600, 700, 70, 79, false)
	b.BootID = "new-boot"
	sum := batteryTotals([]BatterySample{a, b}, nil, 900, 1700)
	if sum.Observed != 0 || sum.Drop != 0 || math.IsNaN(sum.Sleeping) {
		t.Fatal("unobserved time invented", sum)
	}
}
func TestBatteryMidnightWakeBelongsToOneDay(t *testing.T) {
	midnight := time.Date(2026, 10, 17, 0, 0, 0, 0, china).Unix()
	wakes := []BatteryWake{{At: midnight, Reason: "rtc"}}
	if batteryTotals(nil, wakes, midnight-86400, midnight).RTC != 0 || batteryTotals(nil, wakes, midnight, midnight+86400).RTC != 1 {
		t.Fatal("midnight wake double counted")
	}
}
func TestBatteryPersistsPrivateHistoryAndBoundsGraph(t *testing.T) {
	s := testService(t)
	s.loadBattery()
	now := time.Now()
	s.batteryReader = func() (BatteryReading, error) { return BatteryReading{Percent: 76, Status: "Discharging"}, nil }
	s.pollBattery(now, uptime(), true)
	path := filepath.Join(s.root, "battery", batteryDate(now.Unix())+".json")
	info, e := os.Stat(path)
	if e != nil || info.Mode().Perm() != 0600 {
		t.Fatal("private battery history missing", e)
	}
	loaded := &Service{root: s.root, run: s.run}
	loaded.loadBattery()
	if len(loaded.battery.Days[batteryDate(now.Unix())].Samples) != 1 {
		t.Fatal("history lost on service restart")
	}
	day := s.battery.Days[batteryDate(now.Unix())]
	day.Samples = nil
	for i := 0; i < 288; i++ {
		day.Samples = append(day.Samples, batteryPoint(now.Unix()-int64(287-i)*300, float64(i*300+100), float64(i*60+50), 90-i/10, false))
	}
	s.publishBatteryHistoryLocked(now)
	data, e := os.ReadFile(filepath.Join(s.run, "battery.tsv"))
	if e != nil {
		t.Fatal(e)
	}
	count := strings.Count(string(data), "\npoint\t")
	if count < 140 || count > 145 {
		t.Fatal("unbounded or empty graph", count)
	}
}
func TestBatteryDoesNotInventReadingsInSimulator(t *testing.T) {
	s := testService(t)
	s.loadBattery()
	s.pollBattery(time.Now(), uptime(), true)
	if s.battery.Available || len(s.battery.Days) != 0 {
		t.Fatal("simulator reported a real battery")
	}
}
func TestBatteryWakeIsDeduplicatedAndCancellationIsNotFailure(t *testing.T) {
	s := testService(t)
	s.loadBattery()
	s.recordBatteryWakeLocked(2, SleepResult{}, nil, true)
	if len(s.battery.Days) != 0 {
		t.Fatal("normal cancellation counted as a failed wake")
	}
	s.recordBatteryWakeLocked(3, SleepResult{WakeReason: "rtc"}, nil, false)
	s.recordBatteryWakeLocked(3, SleepResult{WakeReason: "rtc"}, nil, false)
	_, wakes := s.batteryDataLocked()
	if len(wakes) != 1 {
		t.Fatal("same wake counted twice")
	}
}
func TestBatteryIgnoresCorruptHistory(t *testing.T) {
	s := testService(t)
	day := batteryDate(time.Now().Unix())
	directory := filepath.Join(s.root, "battery")
	_ = os.MkdirAll(directory, 0700)
	bad := BatteryDay{Version: 1, Date: day, Samples: []BatterySample{{At: time.Now().Unix(), Percent: 150}}}
	data, _ := json.Marshal(bad)
	_ = os.WriteFile(filepath.Join(directory, day+".json"), data, 0600)
	s.loadBattery()
	if len(s.battery.Days) != 0 {
		t.Fatal("corrupt readings became a real curve")
	}
}

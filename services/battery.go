package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

type BatteryReading struct {
	Percent int
	Status  string
	Powered bool
}
type BatterySample struct {
	At           int64  `json:"at"`
	BootID       string `json:"boot_id"`
	Boot, Active float64
	Percent      int    `json:"percent"`
	Status       string `json:"status"`
	Powered      bool   `json:"powered"`
}
type BatteryWake struct {
	ID     string
	At     int64
	Reason string
	Failed bool
}
type BatteryDay struct {
	Version int
	Date    string
	Samples []BatterySample
	Wakes   []BatteryWake
}
type BatteryState struct {
	Days                map[string]*BatteryDay
	Available           bool
	Current             BatterySample
	Message             string
	NextBoot, SavedBoot float64
	Revision            uint64
	Dirty               bool
}
type BatteryTotals struct {
	Drop                        int
	Observed, Sleeping          float64
	RTC, Power, Other, Failures int
	EndPercent                  int
}

func readBattery() (BatteryReading, error) {
	base := "/sys/class/power_supply/bd7181x_bat/"
	percent, e := strconv.Atoi(readPower(base + "capacity"))
	if e != nil || percent < 0 || percent > 100 {
		return BatteryReading{}, fmt.Errorf("battery capacity unavailable")
	}
	status := readPower(base + "status")
	powered := status == "Charging" || readPower("/sys/class/power_supply/bd7181x_ac/online") == "1" || readPower("/sys/class/power_supply/imx6_usb_charger/online") == "1"
	return BatteryReading{percent, status, powered}, nil
}
func batteryDate(at int64) string { return time.Unix(at, 0).In(china).Format("2006-01-02") }
func (s *Service) loadBattery() {
	s.battery.Days = map[string]*BatteryDay{}
	s.battery.Revision = uint64(uint32(time.Now().UnixNano()) & 0x7fffffff)
	directory := filepath.Join(s.root, "battery")
	entries, _ := os.ReadDir(directory)
	today := time.Now().In(china)
	oldest := today.AddDate(0, 0, -7).Format("2006-01-02")
	latest := today.Format("2006-01-02")
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		day := strings.TrimSuffix(entry.Name(), ".json")
		if parsed, e := time.Parse("2006-01-02", day); e != nil || parsed.Format("2006-01-02") != day {
			continue
		}
		path := filepath.Join(directory, entry.Name())
		if day < oldest {
			_ = os.Remove(path)
			continue
		}
		if day > latest {
			continue
		}
		info, e := entry.Info()
		if e != nil || !info.Mode().IsRegular() || info.Size() > 256*1024 {
			continue
		}
		data, e := os.ReadFile(path)
		var record BatteryDay
		if e != nil || json.Unmarshal(data, &record) != nil || record.Version != 1 || record.Date != day || len(record.Samples) > 600 || len(record.Wakes) > 256 {
			continue
		}
		valid := true
		for _, p := range record.Samples {
			if p.Percent < 0 || p.Percent > 100 || batteryDate(p.At) != day || math.IsNaN(p.Boot) || math.IsNaN(p.Active) || math.IsInf(p.Boot, 0) || math.IsInf(p.Active, 0) || p.Boot < 0 || p.Active < 0 {
				valid = false
				break
			}
		}
		if valid {
			s.battery.Days[day] = &record
		}
	}
}
func (s *Service) batteryDayLocked(at int64) *BatteryDay {
	if s.battery.Days == nil {
		s.battery.Days = map[string]*BatteryDay{}
	}
	day := batteryDate(at)
	if s.battery.Days[day] == nil {
		s.battery.Days[day] = &BatteryDay{Version: 1, Date: day}
	}
	oldest := time.Unix(at, 0).In(china).AddDate(0, 0, -7).Format("2006-01-02")
	for date := range s.battery.Days {
		if date < oldest {
			delete(s.battery.Days, date)
			_ = os.Remove(filepath.Join(s.root, "battery", date+".json"))
		}
	}
	return s.battery.Days[day]
}
func (s *Service) saveBatteryDayLocked(day *BatteryDay) {
	data, e := json.Marshal(day)
	if e == nil {
		e = atomicWrite(filepath.Join(s.root, "battery", day.Date+".json"), data, 0600)
	}
	if e != nil {
		s.battery.Message = "历史保存失败，当前电量仍可查看"
		return
	}
	s.battery.Message = ""
	s.battery.SavedBoot = uptime()
	s.battery.Dirty = false
}
func (s *Service) pollBattery(now time.Time, boot float64, force bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !force && boot < s.battery.NextBoot {
		return
	}
	s.battery.NextBoot = boot + 300
	reader := s.batteryReader
	if reader == nil {
		if s.simulate {
			return
		}
		reader = readBattery
	}
	reading, e := reader()
	if e != nil {
		s.battery.Available = false
		s.battery.Message = "无法读取电池"
		return
	}
	if reading.Percent < 0 || reading.Percent > 100 {
		return
	}
	point := BatterySample{At: now.Unix(), BootID: bootID(), Boot: boot, Active: activeClock(), Percent: reading.Percent, Status: clean(reading.Status, 32), Powered: reading.Powered}
	first := !s.battery.Available
	changed := point.Powered != s.battery.Current.Powered || point.Status != s.battery.Current.Status
	if s.battery.Dirty && batteryDate(s.battery.Current.At) != batteryDate(point.At) {
		if previous := s.battery.Days[batteryDate(s.battery.Current.At)]; previous != nil {
			s.saveBatteryDayLocked(previous)
		}
	}
	s.battery.Current = point
	s.battery.Available = true
	day := s.batteryDayLocked(point.At)
	if n := len(day.Samples); n > 0 && day.Samples[n-1].At == point.At {
		day.Samples[n-1] = point
	} else {
		day.Samples = append(day.Samples, point)
	}
	if len(day.Samples) > 600 {
		day.Samples = append([]BatterySample(nil), day.Samples[len(day.Samples)-600:]...)
	}
	s.battery.Dirty = true
	s.battery.Revision++
	if first || changed || force || boot-s.battery.SavedBoot >= 900 {
		s.saveBatteryDayLocked(day)
	}
	s.publishBatteryHistoryLocked(now)
}
func (s *Service) recordBatteryWakeLocked(cycle uint64, result SleepResult, failure error, cancelled bool) {
	if cancelled {
		return
	}
	at := time.Now().Unix()
	day := s.batteryDayLocked(at)
	id := fmt.Sprintf("%s-%d", bootID(), cycle)
	for _, event := range day.Wakes {
		if event.ID == id {
			return
		}
	}
	day.Wakes = append(day.Wakes, BatteryWake{ID: id, At: at, Reason: result.WakeReason, Failed: failure != nil})
	if len(day.Wakes) > 256 {
		day.Wakes = append([]BatteryWake(nil), day.Wakes[len(day.Wakes)-256:]...)
	}
	s.battery.Revision++
	s.saveBatteryDayLocked(day)
	s.publishBatteryHistoryLocked(time.Now())
}
func batteryInterval(a, b BatterySample) (float64, float64, bool) {
	seconds := b.Boot - a.Boot
	active := b.Active - a.Active
	if a.BootID == "" || a.BootID != b.BootID || b.At <= a.At || seconds <= 0 || seconds > 2700 || active < 0 || active > seconds+2 || math.Abs(float64(b.At-a.At)-seconds) > 120 {
		return 0, 0, false
	}
	sleep := math.Max(0, math.Min(seconds, seconds-active))
	return seconds, sleep, true
}
func batteryTotals(samples []BatterySample, wakes []BatteryWake, from, to int64) BatteryTotals {
	out := BatteryTotals{EndPercent: -1}
	for i, p := range samples {
		if p.At >= from && p.At < to {
			out.EndPercent = p.Percent
		}
		if i == 0 {
			continue
		}
		previous := samples[i-1]
		seconds, sleep, valid := batteryInterval(previous, p)
		if !valid || p.At <= from || previous.At >= to {
			continue
		}
		begin, end := previous.At, p.At
		if begin < from {
			begin = from
		}
		if end > to {
			end = to
		}
		fraction := float64(end-begin) / float64(p.At-previous.At)
		out.Observed += seconds * fraction
		out.Sleeping += sleep * fraction
		// Attribute observed net discharge to the sample endpoint. Charging
		// intervals and gaps are never turned into a fictional discharge rate.
		if !previous.Powered && !p.Powered && p.At >= from && p.At < to {
			out.Drop += previous.Percent - p.Percent
		}
	}
	if out.Drop < 0 {
		out.Drop = 0
	}
	for _, event := range wakes {
		if event.At < from || event.At >= to {
			continue
		}
		if event.Failed {
			out.Failures++
			continue
		}
		switch event.Reason {
		case "rtc":
			out.RTC++
		case "power-or-usb":
			out.Power++
		default:
			out.Other++
		}
	}
	return out
}
func (s *Service) batteryDataLocked() ([]BatterySample, []BatteryWake) {
	var samples []BatterySample
	var wakes []BatteryWake
	for _, day := range s.battery.Days {
		samples = append(samples, day.Samples...)
		wakes = append(wakes, day.Wakes...)
	}
	sort.SliceStable(samples, func(i, j int) bool { return samples[i].At < samples[j].At })
	return samples, wakes
}
func (s *Service) publishBatteryHistoryLocked(now time.Time) {
	if s.run == "" {
		return
	}
	samples, wakes := s.batteryDataLocked()
	end := now.Unix()
	start := end - 86400
	var b strings.Builder
	fmt.Fprintf(&b, "paperos-battery-v1\t%d\n", s.battery.Revision)
	sum := batteryTotals(samples, wakes, start, end+1)
	fmt.Fprintf(&b, "summary\t%d\t%d\t%d\t%.0f\t%.0f\t%d\t%d\t%d\t%d\n", start, end, sum.Drop, sum.Sleeping, sum.Observed, sum.RTC, sum.Power, sum.Other, sum.Failures)
	for offset := -6; offset <= 0; offset++ {
		day := now.In(china).AddDate(0, 0, offset)
		from := time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, china).Unix()
		to := from + 86400
		if to > end {
			to = end + 1
		}
		total := batteryTotals(samples, wakes, from, to)
		fmt.Fprintf(&b, "day\t%s\t%d\t%.0f\t%.0f\t%d\t%d\n", day.Format("2006-01-02"), total.Drop, total.Observed, total.Sleeping, total.RTC+total.Power+total.Other, total.EndPercent)
	}
	// Ten-minute buckets keep the renderer bounded; gaps remain explicit.
	lastBucket := int64(-1)
	lastIndex := -1
	for i, p := range samples {
		if p.At < start || p.At > end {
			continue
		}
		bucket := p.At / 600
		if bucket == lastBucket {
			continue
		}
		connected := false
		if lastIndex >= 0 {
			_, _, connected = batteryInterval(samples[lastIndex], p)
		}
		fmt.Fprintf(&b, "point\t%d\t%d\t%t\t%t\n", p.At, p.Percent, p.Powered, connected)
		lastBucket = bucket
		lastIndex = i
	}
	if e := atomicWrite(filepath.Join(s.run, "battery.tsv"), []byte(b.String()), 0644); e != nil {
		s.battery.Message = "统计画面暂不可用"
	}
}
func (s *Service) publishBatteryLocked(b *strings.Builder) {
	path := filepath.Join(s.run, "battery.tsv")
	fmt.Fprintf(b, "battery\t%t\t%d\t%s\t%t\t%d\t%s\t%d\t%s\n", s.battery.Available, s.battery.Current.Percent, field(s.battery.Current.Status), s.battery.Current.Powered, s.battery.Current.At, field(path), s.battery.Revision, field(s.battery.Message))
}

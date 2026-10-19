package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type SleepConfig struct {
	Version               int
	Enabled, USBKeepAwake bool
}
type SleepState struct {
	Available, Busy, Requested, USB bool
	Phase, Message, LastWake        string
	NextWake, LastAt                int64
	LastSeconds                     float64
	Cycle, LockGeneration           uint64
	LockedSince, AwakeUntil         float64
	Failures                        int
	child                           *os.Process
}
type SleepResult struct {
	SuspendedSeconds, ActiveSeconds, ElapsedSeconds float64
	WakeReason                                      string
	RTCBefore, RTCAfter                             uint64
	RecoveryWarning                                 string
}
type SleepMarker struct {
	Complete bool
	Cycle    uint64
	BootID   string
	At       int64
	Result   SleepResult
	Error    string
}

func (s *Service) sleepMarkerPath() string { return filepath.Join(s.root, "sleep-cycle.json") }
func (s *Service) loadSleep() {
	if s.cfg.Sleep.Version == 0 {
		s.cfg.Sleep = SleepConfig{Version: 1, Enabled: true, USBKeepAwake: true}
	}
	s.sleep.Phase = "awake"
	s.sleep.Available = !s.simulate && sleepHardwareAvailable()
	var marker SleepMarker
	if data, e := os.ReadFile(s.sleepMarkerPath()); e == nil && json.Unmarshal(data, &marker) == nil {
		if marker.Complete {
			s.sleep.LastAt = marker.At
			s.sleep.LastSeconds = marker.Result.SuspendedSeconds
			s.sleep.LastWake = marker.Result.WakeReason
		} else {
			s.cfg.Sleep.Enabled = false
			s.sleep.Phase = "error"
			s.sleep.Message = "上次休眠未完成，自动休眠已暂停"
			_ = s.saveLocked()
		}
	}
}
func (s *Service) cancelSleepLocked() {
	_ = os.Remove(filepath.Join(s.run, "sleep-request"))
	if s.sleep.child != nil {
		_ = s.sleep.child.Signal(os.Interrupt)
	}
}
func (s *Service) sleepCommandLocked(v url.Values, boot float64) (bool, error) {
	switch v.Get("cmd") {
	case "sleep-enable", "sleep-usb":
		if v.Get("enabled") != "true" && v.Get("enabled") != "false" {
			return true, errors.New("请选择开或关")
		}
		old := s.cfg.Sleep
		if v.Get("cmd") == "sleep-enable" {
			s.cfg.Sleep.Enabled = v.Get("enabled") == "true"
			s.sleep.Failures = 0
		} else {
			s.cfg.Sleep.USBKeepAwake = v.Get("enabled") == "true"
		}
		s.cfg.Sleep.Version = 1
		if e := s.saveLocked(); e != nil {
			s.cfg.Sleep = old
			return true, e
		}
		s.sleep.AwakeUntil = boot + 15
		s.sleep.Message = ""
		if !s.sleep.Busy {
			s.sleep.Phase = "awake"
		}
		return true, nil
	case "sleep-now":
		if !s.sleep.Available {
			return true, errors.New("当前硬件或模拟环境未启用真正休眠")
		}
		s.refreshExternalPowerLocked(boot)
		if reason := s.powerSleepBlockLocked(); reason != "" {
			return true, errors.New(reason)
		}
		if s.cfg.Active != nil {
			return true, errors.New("请先停止当前提醒")
		}
		if s.receiveUntil.After(time.Now()) || s.uploading || s.pending != nil {
			return true, errors.New("请先关闭接收应用并完成传输")
		}
		_, e := s.lockCommandLocked(url.Values{"cmd": {"lock-now"}}, boot)
		if e != nil {
			return true, e
		}
		s.sleep.Requested = true
		s.sleep.LockGeneration = s.lock.Generation
		s.sleep.LockedSince = boot - 15
		s.sleep.AwakeUntil = 0
		return true, nil
	}
	return false, nil
}

// Timer deadlines use boottime, so both sleep and wall-clock corrections preserve duration.
func (s *Service) nextSleepWakeLocked(now time.Time, boot float64) int64 {
	next := now.Unix() + 1800
	for _, a := range s.cfg.Alarms {
		if a.Enabled {
			at := a.Next
			if at == 0 {
				at = nextAlarm(a, now)
			}
			if at > 0 && at-2 < next {
				next = at - 2
			}
		}
	}
	for _, timer := range []Timer{s.cfg.Timer, s.cfg.Snooze} {
		if timer.State == "running" {
			at := now.Unix() + int64(timerRemaining(&timer, now, boot, bootID())) - 2
			if at < next {
				next = at
			}
		}
	}
	return next
}
func (s *Service) sleepBlockLocked(now time.Time, boot float64) string {
	if !s.sleep.Available {
		return "当前环境不支持真正休眠"
	}
	if reason := s.powerSleepBlockLocked(); reason != "" {
		return reason
	}
	if !s.cfg.Sleep.Enabled && !s.sleep.Requested {
		return "自动休眠已关闭"
	}
	if !s.lock.Locked {
		return "使用中，锁屏后休眠"
	}
	if s.cfg.Active != nil {
		return "提醒中，保持唤醒"
	}
	if s.receiveUntil.After(now) || s.uploading || s.pending != nil {
		return "接收应用中，保持唤醒"
	}
	if s.cfg.Sleep.USBKeepAwake && s.sleep.USB && !s.sleep.Requested {
		return "USB 调试连接中，保持唤醒"
	}
	if boot < s.sleep.AwakeUntil {
		return "唤醒后短暂更新数据"
	}
	if boot-s.sleep.LockedSince < 15 && !s.sleep.Requested {
		return "锁屏后 15 秒进入休眠"
	}
	if s.net.Busy || s.weatherBusy || s.spotlightBusy || s.clockBusy || s.locationSearch.Busy || s.mihome.Busy || s.tailnet.Busy {
		return "正在联网处理，完成后休眠"
	}
	if s.store != nil && s.store.Busy {
		return "正在下载或安装应用，完成后休眠"
	}
	if s.nextSleepWakeLocked(now, boot) <= now.Unix()+8 {
		return "提醒即将到达，保持唤醒"
	}
	return ""
}
func (s *Service) publishSleepLocked(b *strings.Builder) {
	fmt.Fprintf(b, "sleep\t%t\t%t\t%s\t%s\t%d\t%d\t%g\t%s\t%d\t%t\t%t\n", s.cfg.Sleep.Enabled, s.sleep.Available, field(s.sleep.Phase), field(s.sleep.Message), s.sleep.NextWake, s.sleep.LastAt, s.sleep.LastSeconds, field(s.sleep.LastWake), s.sleep.Cycle, s.cfg.Sleep.USBKeepAwake, s.sleep.USB)
}
func (s *Service) pollSleep(now time.Time, boot float64) {
	s.mu.Lock()
	s.refreshExternalPowerLocked(boot)
	if s.sleep.Busy {
		if data, e := os.ReadFile(filepath.Join(s.run, "sleep-progress")); e == nil && strings.TrimSpace(string(data)) == fmt.Sprintf("resumed %d", s.sleep.Cycle) {
			s.sleep.Phase = "resuming"
			s.sleep.Message = "已唤醒，正在恢复连接"
		}
		s.mu.Unlock()
		return
	}
	s.sleep.USB = sleepUSBConnected()
	if s.lock.Generation != s.sleep.LockGeneration {
		s.sleep.LockGeneration = s.lock.Generation
		s.sleep.LockedSince = boot
	}
	if reason := s.sleepBlockLocked(now, boot); reason != "" {
		if s.sleep.Phase != "error" {
			s.sleep.Phase = "awake"
			s.sleep.Message = reason
		}
		s.sleep.NextWake = 0
		s.mu.Unlock()
		return
	}
	s.sleep.Busy = true
	s.sleep.Requested = false
	s.sleep.Phase = "preparing"
	s.sleep.Message = "准备休眠，短按电源键可取消"
	s.sleep.Cycle = uint64(uint32(now.UnixNano()))
	if s.sleep.Cycle == 0 {
		s.sleep.Cycle = 1
	}
	cycle, generation, deadline := s.sleep.Cycle, s.lock.Generation, s.nextSleepWakeLocked(now, boot)
	s.sleep.NextWake = deadline
	e := atomicWrite(filepath.Join(s.run, "sleep-request"), []byte(fmt.Sprintf("%d\n", cycle)), 0600)
	if e != nil {
		s.sleep.Busy = false
		s.sleep.Phase = "error"
		s.sleep.Message = "休眠准备失败"
		s.sleep.AwakeUntil = boot + 120
		s.mu.Unlock()
		return
	}
	s.mu.Unlock()
	s.publish()
	go s.performSleep(cycle, generation, deadline)
}
func (s *Service) sleepReady(cycle, generation uint64) bool {
	data, e := os.ReadFile(filepath.Join(s.run, "sleep-display.state"))
	if e != nil {
		return false
	}
	fields := strings.Fields(string(data))
	if len(fields) != 5 || fields[0] != "ready" {
		return false
	}
	c, e1 := strconv.ParseUint(fields[1], 10, 64)
	g, e2 := strconv.ParseUint(fields[2], 10, 64)
	at, e3 := strconv.ParseFloat(fields[3], 64)
	return e1 == nil && e2 == nil && e3 == nil && c == cycle && g == generation && math.Abs(uptime()-at) < 8
}
func (s *Service) sleepIntentCurrent(cycle uint64) bool {
	data, e := os.ReadFile(filepath.Join(s.run, "sleep-request"))
	return e == nil && strings.TrimSpace(string(data)) == strconv.FormatUint(cycle, 10)
}
func (s *Service) performSleep(cycle, generation uint64, deadline int64) {
	var result SleepResult
	var failure error
	for i := 0; i < 100; i++ {
		s.mu.Lock()
		s.refreshExternalPowerLocked(uptime())
		valid := s.lock.Locked && s.lock.Generation == generation && s.sleep.Cycle == cycle && s.sleepIntentCurrent(cycle)
		s.mu.Unlock()
		if !valid {
			failure = errors.New("休眠已取消")
			break
		}
		if s.sleepReady(cycle, generation) {
			break
		}
		if i == 99 {
			failure = errors.New("屏幕未完成休眠画面，已保留唤醒状态")
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if failure == nil {
		s.pollBattery(time.Now(), uptime(), true)
		marker := SleepMarker{Cycle: cycle, BootID: bootID(), At: time.Now().Unix()}
		data, _ := json.Marshal(marker)
		failure = atomicWrite(s.sleepMarkerPath(), data, 0600)
		if failure == nil {
			s.networkMu.Lock()
			s.mu.Lock()
			s.refreshExternalPowerLocked(uptime())
			valid := s.sleepIntentCurrent(cycle) && s.lock.Locked && s.lock.Generation == generation
			s.mu.Unlock()
			if !valid {
				failure = errors.New("休眠已取消")
			} else if s.sleepRunner != nil {
				result, failure = s.sleepRunner(cycle, deadline)
			} else {
				command := exec.Command("/usr/sbin/paperos-services", "power-suspend", strconv.FormatUint(cycle, 10), strconv.FormatInt(deadline, 10))
				var output bytes.Buffer
				command.Stdout = &output
				logfile, _ := os.OpenFile(filepath.Join(s.run, "sleep-worker.log"), os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0600)
				if logfile != nil {
					command.Stderr = logfile
				}
				failure = command.Start()
				if failure == nil {
					s.mu.Lock()
					s.sleep.child = command.Process
					s.mu.Unlock()
					failure = command.Wait()
					s.mu.Lock()
					s.sleep.child = nil
					s.mu.Unlock()
				}
				if logfile != nil {
					_ = logfile.Close()
				}
				if failure == nil {
					failure = json.Unmarshal(output.Bytes(), &result)
				}
			}
			s.networkMu.Unlock()
		}
	}
	s.mu.Lock()
	s.refreshExternalPowerLocked(uptime())
	s.sleep.Busy = false
	s.sleep.AwakeUntil = uptime() + 20
	s.sleep.NextWake = 0
	s.sleep.Phase = "awake"
	cancelled := failure != nil && (!s.lock.Locked || s.lock.Generation != generation || !s.sleepIntentCurrent(cycle))
	if cancelled {
		s.sleep.Message = s.powerSleepBlockLocked()
		if s.sleep.Message == "" {
			s.sleep.Message = "休眠已取消"
		}
	} else if failure != nil {
		s.sleep.Failures++
		s.sleep.AwakeUntil = uptime() + 120
		s.sleep.Phase = "error"
		s.sleep.Message = "休眠未完成，保持唤醒"
		if s.sleep.Failures >= 3 {
			s.cfg.Sleep.Enabled = false
			_ = s.saveLocked()
			s.sleep.Message = "休眠连续失败，自动休眠已暂停"
		}
		log.Printf("suspend: %v", failure)
	} else {
		s.sleep.Failures = 0
		s.sleep.LastAt = time.Now().Unix()
		s.sleep.LastSeconds = result.SuspendedSeconds
		s.sleep.LastWake = result.WakeReason
		s.sleep.Message = "已从休眠恢复"
		if result.RecoveryWarning != "" {
			s.sleep.Message = "已唤醒，部分连接未恢复，请检查网络"
		}
	}
	marker := SleepMarker{Complete: true, Cycle: cycle, BootID: bootID(), At: time.Now().Unix(), Result: result}
	if failure != nil {
		marker.Error = failure.Error()
	}
	data, _ := json.Marshal(marker)
	_ = atomicWrite(s.sleepMarkerPath(), data, 0600)
	s.recordBatteryWakeLocked(cycle, result, failure, cancelled)
	s.cancelSleepLocked()
	s.mu.Unlock()
	s.pollBattery(time.Now(), uptime(), true)
	s.tick(time.Now(), uptime(), bootID())
	s.pollNetwork()
	if failure == nil {
		// The ticker counts awake seconds. Explicitly poll after resume so a
		// short refresh window cannot postpone work for several sleep cycles.
		s.pollClock()
		go s.refreshWeather()
		s.pollSpotlight(time.Now())
		s.pollMiHome(true)
	}
	s.publish()
}

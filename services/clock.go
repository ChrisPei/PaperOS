package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"os/exec"
	"syscall"
	"time"
)

type ClockConfig struct {
	Automatic bool
	LastSync  int64
	Source    string
}

type ClockSample struct {
	At, Measured time.Time
	Source       string
}

const ntpEpoch = int64(2208988800)

func ntpTimestamp(data []byte) time.Time {
	seconds := int64(binary.BigEndian.Uint32(data)) - ntpEpoch
	if seconds < 1577836800 { // Resolve the 2036 NTP era rollover.
		seconds += 1 << 32
	}
	nanos := int64(binary.BigEndian.Uint32(data[4:])) * 1e9 >> 32
	return time.Unix(seconds, nanos)
}

func putNTPTimestamp(data []byte, at time.Time) {
	binary.BigEndian.PutUint32(data, uint32(at.Unix()+ntpEpoch))
	binary.BigEndian.PutUint32(data[4:], uint32(uint64(at.Nanosecond())<<32/1e9))
}

func decodeNTP(packet, request []byte, elapsed time.Duration) (time.Time, error) {
	if len(packet) < 48 || len(request) != 48 || elapsed < 0 || elapsed > 4*time.Second {
		return time.Time{}, errors.New("invalid NTP length or delay")
	}
	version := (packet[0] >> 3) & 7
	if packet[0]>>6 == 3 || (version != 3 && version != 4) || packet[0]&7 != 4 || packet[1] == 0 || packet[1] > 15 {
		return time.Time{}, errors.New("time server is not synchronized")
	}
	if !bytes.Equal(packet[24:32], request[40:48]) || bytes.Equal(packet[32:40], make([]byte, 8)) || bytes.Equal(packet[40:48], make([]byte, 8)) {
		return time.Time{}, errors.New("unmatched NTP reply")
	}
	received, sent := ntpTimestamp(packet[32:40]), ntpTimestamp(packet[40:48])
	processing := sent.Sub(received)
	if processing < 0 || processing > elapsed+10*time.Millisecond || sent.Unix() < 1577836800 || sent.Unix() > 2147483647 {
		return time.Time{}, errors.New("invalid server time")
	}
	delay := elapsed - processing
	if delay < 0 {
		delay = 0
	}
	return sent.Add(delay / 2), nil
}

func queryNTP(ctx context.Context, address string) (ClockSample, error) {
	ctx, cancel := context.WithTimeout(ctx, 4*time.Second)
	defer cancel()
	connection, err := (&net.Dialer{}).DialContext(ctx, "udp4", address)
	if err != nil {
		return ClockSample{}, err
	}
	defer connection.Close()
	stop := context.AfterFunc(ctx, func() { connection.Close() })
	defer stop()
	deadline, _ := ctx.Deadline()
	if err = connection.SetDeadline(deadline); err != nil {
		return ClockSample{}, err
	}
	request := make([]byte, 48)
	request[0] = 4<<3 | 3
	start := time.Now()
	putNTPTimestamp(request[40:], start)
	if _, err = connection.Write(request); err != nil {
		return ClockSample{}, err
	}
	reply := make([]byte, 513)
	n, err := connection.Read(reply)
	measured := time.Now()
	if err != nil || n > 512 {
		return ClockSample{}, fmt.Errorf("NTP read: %v", err)
	}
	if difference := measured.Sub(start) - time.Duration(measured.UnixNano()-start.UnixNano()); difference > 100*time.Millisecond || difference < -100*time.Millisecond {
		return ClockSample{}, errors.New("clock changed during NTP request")
	}
	at, err := decodeNTP(reply[:n], request, measured.Sub(start))
	return ClockSample{At: at, Measured: measured, Source: address}, err
}

func networkTime(ctx context.Context) (ClockSample, error) {
	for _, host := range []string{"ntp.aliyun.com", "ntp1.aliyun.com", "ntp2.aliyun.com"} {
		sample, err := queryNTP(ctx, net.JoinHostPort(host, "123"))
		if err == nil {
			sample.Source = host
			return sample, nil
		}
		if ctx.Err() != nil {
			break
		}
	}
	return ClockSample{}, errors.New("时间服务器暂不可用，请稍后重试")
}

func setSystemClock(at time.Time) error {
	// The retained 32-bit KT3 kernel uses the legacy time32 syscall.
	if at.Unix() < 946684800 || at.Unix() > 2147483647 {
		return errors.New("时间超出当前设备内核支持的范围")
	}
	tv := syscall.NsecToTimeval(at.UnixNano())
	return syscall.Settimeofday(&tv)
}

func writeHardwareClock() error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	return exec.CommandContext(ctx, "/sbin/hwclock", "-w", "-u").Run()
}

func (s *Service) rebaseClockLocked(at time.Time, boot float64, id string) {
	for _, timer := range []*Timer{&s.cfg.Timer, &s.cfg.Snooze} {
		if timer.State == "running" {
			timer.WallDeadline = at.Unix() + int64(timerRemaining(timer, at, boot, id))
		}
	}
	for i := range s.cfg.Alarms {
		if s.cfg.Alarms[i].Enabled {
			s.cfg.Alarms[i].Next = nextAlarm(s.cfg.Alarms[i], at)
		}
	}
}

func (s *Service) applyClockLocked(at time.Time) (bool, error) {
	if s.simulate {
		return false, errors.New("模拟环境不修改系统时钟")
	}
	setter := s.clockSetter
	if setter == nil {
		setter = setSystemClock
	}
	if err := setter(at); err != nil {
		return false, errors.New("设置系统时间失败：" + err.Error())
	}
	s.rebaseClockLocked(at, uptime(), bootID())
	rtc := s.clockRTC
	if rtc == nil {
		rtc = writeHardwareClock
	}
	return rtc() == nil, nil
}

func (s *Service) cancelClockLocked() {
	if s.clockCancel != nil {
		s.clockCancel()
		s.clockCancel = nil
	}
	s.clockRun++
	s.clockBusy = false
}

func (s *Service) startClockSyncLocked() error {
	if s.sleep.Busy {
		return errors.New("正在准备休眠，稍后再同步")
	}
	if !s.cfg.WiFi || s.cfg.Airplane || !s.net.Connected {
		return errors.New("请先连接 Wi-Fi")
	}
	if s.simulate {
		return errors.New("模拟环境不修改系统时钟")
	}
	if s.clockBusy {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 14*time.Second)
	s.clockCancel = cancel
	s.clockRun++
	run := s.clockRun
	s.clockBusy = true
	s.clockMessage = "正在同步…"
	s.clockNext = time.Now().Add(5 * time.Minute)
	query := s.clockQuery
	if query == nil {
		query = networkTime
	}
	go func() {
		defer cancel()
		sample, err := query(ctx)
		s.mu.Lock()
		if run != s.clockRun {
			s.mu.Unlock()
			return
		}
		s.clockCancel = nil
		s.clockBusy = false
		if err == nil && (!s.cfg.WiFi || s.cfg.Airplane || !s.net.Connected || ctx.Err() != nil) {
			err = errors.New("同步已取消")
		}
		if err == nil {
			at := sample.At.Add(time.Since(sample.Measured))
			var rtc bool
			rtc, err = s.applyClockLocked(at)
			if err == nil {
				s.cfg.Clock.LastSync = at.Unix()
				s.cfg.Clock.Source = sample.Source
				s.clockMessage = "同步成功"
				if !rtc {
					s.clockMessage = "已同步；硬件时钟写入未确认"
				}
				s.clockNext = time.Now().Add(6 * time.Hour)
			}
		}
		if err != nil {
			s.clockMessage = clean(err.Error(), 80)
		}
		if err = s.saveLocked(); err != nil {
			s.clockMessage = "时间状态保存失败"
		}
		s.mu.Unlock()
		s.publish()
	}()
	return nil
}

func (s *Service) pollClock() {
	s.mu.Lock()
	defer s.mu.Unlock()
	connected := s.cfg.WiFi && !s.cfg.Airplane && s.net.Connected
	reconnected := connected && !s.clockConnected
	s.clockConnected = connected
	if s.sleep.Busy || !s.cfg.Clock.Automatic || !connected || s.simulate || s.clockBusy {
		return
	}
	if reconnected || s.clockNext.IsZero() || !time.Now().Before(s.clockNext) {
		_ = s.startClockSyncLocked()
	}
}

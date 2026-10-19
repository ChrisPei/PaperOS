package main

import (
	"bytes"
	"context"
	"fmt"
	"log"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// Observed on this KT3, not inferred from generic KEY_POWER input mappings.
const kindlePowerPath = "/devices/soc0/soc.2/2100000.aips-bus/21a0000.i2c/i2c-0/0-004b"

func powerEvent(data []byte) (uint64, bool) {
	if len(data) == 0 || len(data) > 8192 || data[len(data)-1] != 0 {
		return 0, false
	}
	parts := bytes.Split(data, []byte{0})
	if string(parts[0]) != "online@"+kindlePowerPath {
		return 0, false
	}
	values := map[string]string{}
	for _, part := range parts[1:] {
		key, value, found := strings.Cut(string(part), "=")
		if !found {
			continue
		}
		if _, duplicate := values[key]; duplicate {
			return 0, false
		}
		values[key] = value
	}
	if values["ACTION"] != "online" || values["DEVPATH"] != kindlePowerPath || values["SUBSYSTEM"] != "i2c" || values["DRIVER"] != "bd7181x" {
		return 0, false
	}
	sequence, e := strconv.ParseUint(values["SEQNUM"], 10, 64)
	return sequence, e == nil && sequence > 0
}
func (s *Service) handlePower(data []byte, boot float64) bool {
	sequence, valid := powerEvent(data)
	if !valid {
		return false
	}
	s.mu.Lock()
	if sequence <= s.powerLastSequence || (s.powerLastAt > 0 && boot-s.powerLastAt < 0.45) {
		s.mu.Unlock()
		return false
	}
	previous := s.lock
	if s.sleep.Busy {
		s.cancelSleepLocked()
	}
	if !s.lock.Locked {
		s.advanceFavoriteLocked(time.Now())
	}
	s.lock.Locked = !s.lock.Locked
	s.lock.LastActivity = boot
	s.lock.Generation++
	if e := s.persistLockLocked(); e != nil {
		s.lock = previous
		s.mu.Unlock()
		log.Printf("power lock: %v", e)
		return false
	}
	s.powerLastAt, s.powerLastSequence = boot, sequence
	state := "unlocked"
	if s.lock.Locked {
		state = "locked"
	}
	_ = atomicWrite(filepath.Join(s.run, "power-key.state"), []byte(fmt.Sprintf("pressed\t%s\t%d\t%d\n", state, sequence, time.Now().Unix())), 0600)
	s.mu.Unlock()
	s.publish()
	log.Printf("Power key: %s", state)
	return true
}
func (s *Service) watchPower(ctx context.Context) {
	fd, e := syscall.Socket(syscall.AF_NETLINK, syscall.SOCK_DGRAM|syscall.SOCK_CLOEXEC, syscall.NETLINK_KOBJECT_UEVENT)
	if e != nil {
		log.Printf("power listener: %v", e)
		return
	}
	defer syscall.Close(fd)
	if e = syscall.Bind(fd, &syscall.SockaddrNetlink{Family: syscall.AF_NETLINK, Groups: 1}); e != nil {
		log.Printf("power bind: %v", e)
		return
	}
	_ = syscall.SetsockoptTimeval(fd, syscall.SOL_SOCKET, syscall.SO_RCVTIMEO, &syscall.Timeval{Sec: 1})
	_ = atomicWrite(filepath.Join(s.run, "power-key.state"), []byte("ready\tbd7181x\n"), 0600)
	buffer := make([]byte, 8193)
	for ctx.Err() == nil {
		n, sender, e := syscall.Recvfrom(fd, buffer, 0)
		if e == syscall.EINTR || e == syscall.EAGAIN {
			continue
		}
		if e != nil {
			log.Printf("power receive: %v", e)
			return
		}
		peer, okay := sender.(*syscall.SockaddrNetlink)
		if !okay || peer.Pid != 0 || n > 8192 {
			continue
		} // accept kernel-origin messages only
		s.handlePower(buffer[:n], uptime())
	}
}

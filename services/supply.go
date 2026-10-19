package main

import "errors"

type ExternalPowerState struct {
	Known, Powered bool
}

// The charger remains online when the battery is full and when USB is not
// configured as a data connection. Battery capacity is irrelevant to this gate.
func externalPowerReading(read func(string) string) (bool, error) {
	ac := read("/sys/class/power_supply/bd7181x_ac/online")
	usb := read("/sys/class/power_supply/imx6_usb_charger/online")
	if ac == "1" || usb == "1" || read("/sys/class/power_supply/bd7181x_bat/status") == "Charging" {
		return true, nil
	}
	if ac == "0" && usb == "0" {
		return false, nil
	}
	return false, errors.New("无法确认外接电源状态")
}

func readExternalPower() (bool, error) { return externalPowerReading(readPower) }

func validPoweredMultiplier(n int) bool { return n == 2 || n == 3 || n == 5 || n == 10 }
func (s *Service) poweredMultiplierLocked() int {
	if validPoweredMultiplier(s.cfg.Lock.PoweredMultiplier) {
		return s.cfg.Lock.PoweredMultiplier
	}
	return 5
}
func (s *Service) effectiveIdleLocked() int {
	seconds := s.cfg.Lock.IdleSeconds
	if s.supply.Powered {
		seconds *= s.poweredMultiplierLocked()
	}
	return seconds
}
func (s *Service) powerSleepBlockLocked() string {
	if !s.supply.Known {
		return "电源状态未知，保持唤醒"
	}
	if s.supply.Powered {
		return "外接电源中，保持唤醒"
	}
	return ""
}
func (s *Service) refreshExternalPowerLocked(boot float64) {
	reader := s.supplyReader
	if reader == nil {
		reader = readExternalPower
		if s.simulate {
			reader = func() (bool, error) { return false, nil }
		}
	}
	powered, e := reader()
	previous := s.supply
	s.supply.Known = e == nil
	if e == nil {
		s.supply.Powered = powered
		if previous.Powered != powered {
			// Start a fresh idle period on either transition. Never overwrite
			// the user's base timeout or unlock a manually locked device.
			s.lock.LastActivity = boot
			s.sleep.LockedSince = boot
			s.sleep.AwakeUntil = max(s.sleep.AwakeUntil, boot+15)
			s.battery.NextBoot = 0
		}
	}
	if s.powerSleepBlockLocked() != "" && (s.sleep.Busy || s.sleep.Requested) {
		s.sleep.Requested = false
		s.cancelSleepLocked()
	}
}
func (s *Service) refreshExternalPower() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.refreshExternalPowerLocked(uptime())
}

package main

import (
	"fmt"
	"strings"
	"testing"
)

func powerPacket(action string, seq int) []byte {
	return []byte(fmt.Sprintf("%s@%s\x00ACTION=%s\x00DEVPATH=%s\x00SUBSYSTEM=i2c\x00DRIVER=bd7181x\x00SEQNUM=%d\x00", action, kindlePowerPath, action, kindlePowerPath, seq))
}
func TestPhysicalPowerPacketTogglesOnceAndIgnoresOtherEvents(t *testing.T) {
	s := testService(t)
	if !s.handlePower(powerPacket("online", 1453), 100) || !s.lock.Locked {
		t.Fatal("observed power press did not lock")
	}
	if s.handlePower(powerPacket("online", 1453), 101) {
		t.Fatal("duplicate sequence toggled again")
	}
	if s.handlePower(powerPacket("online", 1454), 100.1) {
		t.Fatal("switch bounce toggled again")
	}
	if s.handlePower(powerPacket("offline", 1455), 102) {
		t.Fatal("long press acted as a short press")
	}
	if !s.handlePower(powerPacket("online", 1456), 103) || s.lock.Locked {
		t.Fatal("next short press did not unlock")
	}
	for _, packet := range []string{
		strings.ReplaceAll(string(powerPacket("online", 1457)), "bd7181x", "other-driver"),
		strings.ReplaceAll(string(powerPacket("online", 1457)), "online", "change"),
		string(powerPacket("online", 1457)) + "ACTION=online\x00",
		string(powerPacket("online", 1457))[:20],
	} {
		if s.handlePower([]byte(packet), 104) {
			t.Fatal("unrelated/malformed uevent toggled the lock")
		}
	}
}

package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

func readPower(path string) string {
	data, _ := os.ReadFile(path)
	return strings.TrimSpace(string(data))
}
func writePower(path, value string) error {
	file, e := os.OpenFile(path, os.O_WRONLY, 0)
	if e != nil {
		return e
	}
	_, e = file.WriteString(value + "\n")
	closeError := file.Close()
	if e != nil {
		return e
	}
	return closeError
}
func sleepHardwareAvailable() bool {
	return readPower("/sys/class/rtc/rtc0/name") == "bd7181x-rtc" && strings.Contains(" "+readPower("/sys/power/state")+" ", " mem ")
}
func sleepUSBConnected() bool { return readPower("/sys/class/udc/ci_hdrc.0/state") == "configured" }
func activeClock() float64 {
	var ts syscall.Timespec
	_, _, e := syscall.Syscall(syscall.SYS_CLOCK_GETTIME, 1, uintptr(unsafe.Pointer(&ts)), 0)
	if e != 0 {
		return uptime()
	}
	return float64(ts.Sec) + float64(ts.Nsec)/1e9
}
func rtcIRQs() uint64 {
	data, _ := os.ReadFile("/proc/interrupts")
	for _, line := range strings.Split(string(data), "\n") {
		if strings.Contains(line, "bd7181x-rtc") {
			parts := strings.Fields(line)
			if len(parts) > 1 {
				n, _ := strconv.ParseUint(parts[1], 10, 64)
				return n
			}
		}
	}
	return 0
}

type stoppedUI struct {
	pid   int
	start string
}

func uiProcess(pid int) (string, string, bool) {
	return uiProcessAt("/proc", pid)
}

// Standalone native applications are exec'd directly by the launcher. Pause
// their display process as well, without selecting unrelated system services.
func uiProcessAt(proc string, pid int) (string, string, bool) {
	prefix := filepath.Join(proc, strconv.Itoa(pid))
	exe, e := os.Readlink(prefix + "/exe")
	if e != nil {
		return "", "", false
	}
	data, e := os.ReadFile(prefix + "/stat")
	if e != nil {
		return "", "", false
	}
	end := strings.LastIndex(string(data), ") ")
	if end < 0 {
		return "", "", false
	}
	parts := strings.Fields(string(data)[end+2:])
	if len(parts) < 20 {
		return "", "", false
	}
	if exe != "/usr/bin/paperos" {
		const apps = "/var/lib/paperos/apps/"
		if !strings.HasPrefix(exe, apps) || filepath.Clean(exe) != exe || strings.HasSuffix(exe, " (deleted)") {
			return "", "", false
		}
		relative := strings.TrimPrefix(exe, apps)
		id, entry, okay := strings.Cut(relative, "/")
		if !okay || id == "" || strings.HasPrefix(id, ".") || entry == "" {
			return "", "", false
		}
		parent, e := strconv.Atoi(parts[1])
		if e != nil || parent <= 1 || parent == pid {
			return "", "", false
		}
		parentExe, e := os.Readlink(filepath.Join(proc, strconv.Itoa(parent), "exe"))
		if e != nil || parentExe != "/usr/bin/paperos" {
			return "", "", false
		}
	}
	return parts[0], parts[19], true
}
func stopSleepUI() ([]stoppedUI, error) {
	entries, e := os.ReadDir("/proc")
	if e != nil {
		return nil, e
	}
	var stopped []stoppedUI
	for _, entry := range entries {
		pid, e := strconv.Atoi(entry.Name())
		if e != nil {
			continue
		}
		_, start, okay := uiProcess(pid)
		if !okay {
			continue
		}
		if e = syscall.Kill(pid, syscall.SIGSTOP); e != nil {
			continue
		}
		stopped = append(stopped, stoppedUI{pid, start})
	}
	for _, process := range stopped {
		ready := false
		for n := 0; n < 50; n++ {
			state, start, okay := uiProcess(process.pid)
			if !okay || start != process.start || state == "T" || state == "t" {
				ready = true
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
		if !ready {
			return stopped, errors.New("native display did not pause")
		}
	}
	if len(stopped) == 0 {
		return stopped, errors.New("native display is unavailable")
	}
	return stopped, nil
}
func resumeSleepUI(stopped []stoppedUI) {
	for _, p := range stopped {
		_, start, okay := uiProcess(p.pid)
		if okay && start == p.start {
			_ = syscall.Kill(p.pid, syscall.SIGCONT)
		}
	}
}
func powerCommand(name string, args ...string) error {
	command := exec.Command(name, args...)
	command.Stdout = os.Stderr
	command.Stderr = os.Stderr
	return command.Run()
}

// This is a separate child so cleanup always runs before a service restart.
func runSuspendChild(args []string) (failure error) {
	var completed *SleepResult
	defer func() {
		if completed != nil {
			if e := json.NewEncoder(os.Stdout).Encode(completed); failure == nil {
				failure = e
			}
		}
	}()
	if len(args) != 2 || os.Geteuid() != 0 || os.Getenv("PAPEROS_EMULATOR") == "1" || !sleepHardwareAvailable() {
		return errors.New("unsupported suspend worker")
	}
	cycle, e := strconv.ParseUint(args[0], 10, 32)
	if e != nil || cycle == 0 {
		return errors.New("invalid suspend cycle")
	}
	deadline, e := strconv.ParseInt(args[1], 10, 64)
	if e != nil || deadline < time.Now().Unix()+3 || deadline > time.Now().Unix()+1800 {
		return errors.New("invalid RTC deadline")
	}
	request := "/run/paperos/sleep-request"
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
	defer signal.Stop(signals)
	go func() { <-signals; _ = os.Remove(request) }()
	valid := func() bool {
		if readPower(request) != strconv.FormatUint(cycle, 10) {
			return false
		}
		powered, err := readExternalPower()
		if err != nil || powered {
			_ = os.Remove(request)
			return false
		}
		return true
	}
	if !valid() {
		return errors.New("suspend cancelled")
	}
	if readPower("/sys/class/rtc/rtc0/wakealarm") != "" {
		return errors.New("another RTC alarm is already armed")
	}
	stopped, e := stopSleepUI()
	defer resumeSleepUI(stopped)
	if e != nil {
		return e
	}
	async := readPower("/sys/power/pm_async")
	wake := readPower("/sys/class/rtc/rtc0/device/power/wakeup")
	_, usbError := os.Stat("/sys/module/g_ether")
	hadUSB := usbError == nil
	_, wifiError := os.Stat("/sys/module/dhd")
	hadWiFi := wifiError == nil
	blanked, armed := false, false
	defer func() {
		_ = writePower("/sys/power/pm_test", "none")
		if armed {
			_ = writePower("/sys/class/rtc/rtc0/wakealarm", "0")
		}
		_ = writePower("/sys/class/rtc/rtc0/device/power/wakeup", wake)
		_ = writePower("/sys/power/pm_async", async)
		if blanked {
			_ = writePower("/sys/class/graphics/fb0/blank", "0")
		}
		resumeSleepUI(stopped)
		if hadUSB {
			if e := powerCommand("/etc/init.d/S40paperos-usb", "start"); e != nil && completed != nil {
				completed.RecoveryWarning += "USB restore failed; "
			}
		}
		if hadWiFi {
			if e := powerCommand("/etc/init.d/S45paperos-wifi", "start"); e != nil && completed != nil {
				completed.RecoveryWarning += "Wi-Fi restore failed"
			}
		}
	}()
	if hadWiFi {
		if e = powerCommand("/etc/init.d/S45paperos-wifi", "stop"); e != nil {
			return e
		}
		if _, e = os.Stat("/sys/module/dhd"); e == nil {
			return errors.New("wireless driver did not stop")
		}
	}
	if hadUSB {
		_ = powerCommand("/etc/init.d/S40paperos-usb", "stop")
		if e = powerCommand("/sbin/rmmod", "g_ether"); e != nil {
			return e
		}
	}
	if e = writePower("/sys/class/graphics/fb0/blank", "4"); e != nil {
		return e
	}
	blanked = true
	if !valid() {
		return errors.New("suspend cancelled")
	}
	if e = writePower("/sys/power/pm_async", "0"); e != nil {
		return e
	}
	if e = writePower("/sys/power/pm_test", "none"); e != nil {
		return e
	}
	rtc, e := strconv.ParseInt(readPower("/sys/class/rtc/rtc0/since_epoch"), 10, 64)
	if e != nil {
		return e
	}
	seconds := deadline - time.Now().Unix()
	if seconds < 3 {
		return errors.New("reminder is too close for suspend")
	}
	if e = writePower("/sys/class/rtc/rtc0/device/power/wakeup", "enabled"); e != nil {
		return e
	}
	if e = writePower("/sys/class/rtc/rtc0/wakealarm", strconv.FormatInt(rtc+seconds, 10)); e != nil {
		return e
	}
	armed = true
	if readPower("/sys/class/rtc/rtc0/wakealarm") != strconv.FormatInt(rtc+seconds, 10) {
		return errors.New("RTC wake readback failed")
	}
	syscall.Sync()
	count := readPower("/sys/power/wakeup_count")
	if count == "" {
		return errors.New("wakeup count unavailable")
	}
	if !valid() {
		return errors.New("suspend cancelled")
	}
	if e = writePower("/sys/power/wakeup_count", count); e != nil {
		return e
	}
	if !valid() {
		return errors.New("suspend cancelled")
	}
	before, active, boot := rtcIRQs(), activeClock(), uptime()
	if e = writePower("/sys/power/state", "mem"); e != nil {
		return e
	}
	result := SleepResult{ActiveSeconds: activeClock() - active, ElapsedSeconds: uptime() - boot, RTCBefore: before, RTCAfter: rtcIRQs(), WakeReason: "power-or-usb"}
	result.SuspendedSeconds = result.ElapsedSeconds - result.ActiveSeconds
	if result.RTCAfter > result.RTCBefore {
		result.WakeReason = "rtc"
	}
	_ = atomicWrite(filepath.Join("/run/paperos", "sleep-progress"), []byte(fmt.Sprintf("resumed %d\n", cycle)), 0600)
	if result.SuspendedSeconds < 1 {
		return errors.New("suspend returned immediately")
	}
	completed = &result
	return nil
}

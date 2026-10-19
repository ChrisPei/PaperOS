package main

import (
	"context"
	"encoding/hex"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// Public snapshots contain names and profile IDs, never authentication data.
type SavedWiFi struct {
	ID        int
	SSID, Hex string
	Current   bool
}

func parseWPAStatus(out string) map[string]string {
	result := map[string]string{}
	for _, line := range strings.Split(out, "\n") {
		if key, value, okay := strings.Cut(line, "="); okay {
			if key == "ssid" {
				value = decodeSSID(value)
			}
			result[key] = value
		}
	}
	return result
}

func parseSavedWiFi(out string) []SavedWiFi {
	result := []SavedWiFi{}
	for _, line := range strings.Split(out, "\n") {
		fields := strings.SplitN(line, "\t", 4)
		if len(fields) != 4 {
			continue
		}
		id, e := strconv.Atoi(fields[0])
		if e != nil || id < 0 {
			continue
		}
		ssid := decodeSSID(fields[1])
		if !utf8.ValidString(ssid) || len(ssid) == 0 || len(ssid) > 32 {
			continue
		}
		result = append(result, SavedWiFi{ID: id, SSID: ssid, Hex: hex.EncodeToString([]byte(ssid)), Current: strings.Contains(fields[3], "[CURRENT]")})
	}
	return result
}

func (s *Service) savedWiFiProfiles() ([]SavedWiFi, error) {
	out, e := s.wpa("list_networks")
	if e != nil {
		return nil, e
	}
	return parseSavedWiFi(out), nil
}

func (s *Service) refreshSavedNetworks() {
	profiles, e := s.savedWiFiProfiles()
	if e != nil {
		return
	}
	sort.SliceStable(profiles, func(i, j int) bool {
		if profiles[i].Current != profiles[j].Current {
			return profiles[i].Current
		}
		return profiles[i].ID > profiles[j].ID
	})
	seen := map[string]bool{}
	rows := []SavedWiFi{}
	for _, profile := range profiles {
		if seen[profile.Hex] {
			continue
		}
		seen[profile.Hex] = true
		rows = append(rows, profile)
		if len(rows) == 32 {
			break
		}
	}
	s.mu.Lock()
	s.net.Saved = rows
	s.mu.Unlock()
}

func (s *Service) prepareWiFiNetwork(ssid, password string, saved bool) (string, bool, error) {
	if saved {
		profiles, e := s.savedWiFiProfiles()
		if e != nil {
			return "", false, e
		}
		selected := -1
		for _, profile := range profiles {
			if profile.Hex == ssid && (profile.Current || profile.ID > selected) {
				selected = profile.ID
				if profile.Current {
					break
				}
			}
		}
		if selected < 0 {
			return "", false, errors.New("此网络尚未保存，请重新输入密码")
		}
		return strconv.Itoa(selected), false, nil
	}
	index, e := s.wpa("add_network")
	if e != nil {
		return "", false, errors.New("创建无线连接失败")
	}
	id, e := strconv.Atoi(index)
	if e != nil || id < 0 {
		return "", false, errors.New("无线接口未就绪")
	}
	okay := false
	defer func() {
		if !okay {
			_, _ = s.wpa("remove_network", index)
		}
	}()
	if _, e = s.wpa("set_network", index, "ssid", ssid); e != nil {
		return "", false, errors.New("设置无线名称失败")
	}
	if password == "" {
		_, e = s.wpa("set_network", index, "key_mgmt", "NONE")
	} else {
		_, e = s.wpa("set_network", index, "psk", strconv.Quote(password))
	}
	if e != nil {
		return "", false, errors.New("设置无线认证失败")
	}
	okay = true
	return index, true, nil
}

func (s *Service) saveSelectedNetwork(index, ssid string) error {
	profiles, e := s.savedWiFiProfiles()
	if e != nil {
		return e
	}
	// Remove older copies only after the selected profile authenticated.
	for _, profile := range profiles {
		id := strconv.Itoa(profile.ID)
		if id != index && profile.Hex == ssid {
			if _, e = s.wpa("remove_network", id); e != nil {
				return e
			}
			continue
		}
		priority := "0"
		if id == index {
			priority = "10"
		}
		if _, e = s.wpa("set_network", id, "priority", priority); e != nil {
			return e
		}
	}
	if _, e = s.wpa("enable_network", "all"); e != nil {
		return e
	}
	if _, e = s.wpa("save_config"); e != nil {
		return e
	}
	s.refreshSavedNetworks()
	return nil
}

func (s *Service) restoreSavedNetworks() error {
	status, e := s.wpa("status")
	if e != nil {
		return e
	}
	current := parseWPAStatus(status)
	if current["wpa_state"] == "COMPLETED" && current["id"] != "" {
		return s.saveSelectedNetwork(current["id"], hex.EncodeToString([]byte(current["ssid"])))
	}
	if _, e = s.wpa("enable_network", "all"); e != nil {
		return e
	}
	_, e = s.wpa("save_config")
	s.refreshSavedNetworks()
	return e
}

func (s *Service) forgetNetwork(ssid string) {
	raw, e := hex.DecodeString(ssid)
	if e != nil || len(raw) == 0 || len(raw) > 32 {
		return
	}
	s.networkMu.Lock()
	defer s.networkMu.Unlock()
	profiles, e := s.savedWiFiProfiles()
	if e != nil {
		s.networkMessage("无法读取已保存的网络", false)
		return
	}
	for _, profile := range profiles {
		if profile.Hex == ssid {
			if _, e = s.wpa("remove_network", strconv.Itoa(profile.ID)); e != nil {
				s.networkMessage("未能忘记此网络", false)
				return
			}
		}
	}
	if _, e = s.wpa("enable_network", "all"); e == nil {
		_, e = s.wpa("save_config")
	}
	if e != nil {
		s.networkMessage("保存无线配置失败，请重试", false)
		return
	}
	s.refreshSavedNetworks()
	s.pollNetwork()
	s.networkMessage("已忘记此网络", false)
}

func (s *Service) waitNetwork(duration time.Duration) {
	if s.networkWait != nil {
		s.networkWait(duration)
	} else {
		time.Sleep(duration)
	}
}

func (s *Service) acquireNetworkLease() error {
	if s.dhcpRunner != nil {
		return s.dhcpRunner()
	}
	pidData, _ := os.ReadFile("/run/paperos-dhcp.pid")
	if pid, e := strconv.Atoi(strings.TrimSpace(string(pidData))); e == nil && pid > 1 {
		comm, _ := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "comm"))
		if strings.TrimSpace(string(comm)) == "udhcpc" {
			_ = sysKill(pid)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	// A daemonized udhcpc must not inherit an Output pipe and keep it open.
	e := exec.CommandContext(ctx, "/sbin/udhcpc", "-b", "-i", "wlan0", "-p", "/run/paperos-dhcp.pid", "-t", "5", "-T", "2").Run()
	if e == nil && s.wirelessIPv4() == "" {
		return errors.New("DHCP has no address yet")
	}
	return e
}

func (s *Service) renewNetworkLease(ssid string) {
	s.networkMu.Lock()
	defer s.networkMu.Unlock()
	defer func() { s.mu.Lock(); s.net.LeaseBusy = false; s.mu.Unlock() }()
	s.mu.Lock()
	enabled := s.cfg.WiFi && !s.cfg.Airplane && !s.sleep.Busy
	busy := s.net.Busy
	s.mu.Unlock()
	if !enabled || busy {
		return
	}
	out, e := s.wpa("status")
	status := parseWPAStatus(out)
	if e != nil || status["wpa_state"] != "COMPLETED" || status["ssid"] != ssid {
		return
	}
	s.networkMessage("正在获取网络地址", true)
	if e = s.acquireNetworkLease(); e != nil {
		s.networkMessage("已认证，正在等待网络地址", false)
		return
	}
	s.mu.Lock()
	s.net.LeaseSSID = ssid
	s.mu.Unlock()
	s.pollNetwork()
	s.networkMessage("已自动连接保存的网络", false)
}

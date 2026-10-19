package main

import (
	"context"
	"encoding/hex"
	"errors"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type WiFi struct {
	SSID, Hex, Security string
	Level               int
}

func (s *Service) wpa(args ...string) (string, error) {
	if s.wifiControl != nil {
		return s.wifiControl(args...)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "/usr/sbin/wpa_cli", append([]string{"-i", "wlan0"}, args...)...)
	data, e := command.Output()
	result := strings.TrimSpace(string(data))
	if e != nil || strings.Contains(result, "FAIL") {
		return result, errors.New("无线操作失败")
	}
	return result, nil
}
func (s *Service) networkMessage(message string, busy bool) {
	s.mu.Lock()
	s.net.Message = message
	s.net.Busy = busy
	s.mu.Unlock()
}
func (s *Service) applyNetwork() {
	s.networkMu.Lock()
	defer s.networkMu.Unlock()
	s.mu.Lock()
	enabled := s.cfg.WiFi && !s.cfg.Airplane
	s.mu.Unlock()
	if s.simulate {
		s.networkMessage("模拟器未连接无线硬件", false)
		return
	}
	s.networkMessage("正在调整网络", true)
	if !enabled {
		_, _ = exec.Command("/etc/init.d/S45paperos-wifi", "stop").Output()
		_, _ = exec.Command("/sbin/ifconfig", "wlan0", "down").Output()
		s.mu.Lock()
		s.net.Connected = false
		s.net.IP = ""
		s.net.SSID = ""
		s.net.Scan = nil
		s.mu.Unlock()
		s.networkMessage("无线已关闭", false)
		return
	}
	config := "/etc/paperos/wpa_supplicant.conf"
	if _, e := os.Stat(config); os.IsNotExist(e) {
		if e = atomicWrite(config, []byte("ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=CN\n"), 0600); e != nil {
			s.networkMessage("无法保存无线配置", false)
			return
		}
	}
	if _, e := s.wpa("ping"); e != nil {
		if _, e = exec.Command("/etc/init.d/S45paperos-wifi", "start").Output(); e != nil {
			s.networkMessage("无线驱动启动失败", false)
			return
		}
	}
	if e := s.restoreSavedNetworks(); e != nil {
		s.networkMessage("无线已开启，但保存的网络未恢复", false)
		return
	}
	s.networkMessage("无线已开启", false)
	s.pollNetwork()
	go s.scanNetwork()
}
func (s *Service) pollNetwork() {
	s.mu.Lock()
	enabled := s.cfg.WiFi && !s.cfg.Airplane && !s.sleep.Busy
	s.mu.Unlock()
	if !enabled || s.simulate {
		return
	}
	out, e := s.wpa("status")
	if e != nil {
		return
	}
	status := parseWPAStatus(out)
	ip := s.wirelessIPv4()
	s.refreshSavedNetworks()
	s.mu.Lock()
	associated := status["wpa_state"] == "COMPLETED"
	if s.net.LeaseSSID == "" && associated && ip != "" {
		s.net.LeaseSSID = status["ssid"]
	}
	renew := associated && s.net.LeaseSSID != status["ssid"] && !s.net.Busy && !s.net.LeaseBusy
	if renew {
		s.net.LeaseBusy = true
	}
	s.net.Connected = associated && ip != "" && !renew
	s.net.IP = ip
	if !associated || renew {
		s.net.IP = ""
	}
	s.net.SSID = clean(status["ssid"], 40)
	s.mu.Unlock()
	if renew {
		go s.renewNetworkLease(status["ssid"])
	}
}
func (s *Service) wirelessIPv4() string {
	if s.wifiAddress != nil {
		return s.wifiAddress()
	}
	ip := ""
	if iface, e := net.InterfaceByName("wlan0"); e == nil {
		addresses, _ := iface.Addrs()
		for _, address := range addresses {
			if n, _, e := net.ParseCIDR(address.String()); e == nil && n.To4() != nil && !n.IsLinkLocalUnicast() {
				ip = n.String()
				break
			}
		}
	}
	return ip
}
func parseScan(out string) []WiFi {
	result := []WiFi{}
	seen := map[string]bool{}
	for _, line := range strings.Split(out, "\n") {
		parts := strings.SplitN(line, "\t", 5)
		if len(parts) != 5 {
			continue
		}
		level, e := strconv.Atoi(parts[2])
		if e != nil {
			continue
		}
		ssid := decodeSSID(parts[4])
		if ssid == "" || !utf8.ValidString(ssid) || len([]byte(ssid)) > 32 || seen[ssid] {
			continue
		}
		seen[ssid] = true
		security := "开放"
		if strings.Contains(parts[3], "EAP") {
			security = "企业认证"
		} else if strings.Contains(parts[3], "WPA") || strings.Contains(parts[3], "RSN") {
			security = "密码"
		}
		result = append(result, WiFi{clean(ssid, 32), hex.EncodeToString([]byte(ssid)), security, level})
		if len(result) >= 24 {
			break
		}
	}
	return result
}
func decodeSSID(value string) string {
	var b strings.Builder
	for len(value) > 0 {
		if strings.HasPrefix(value, "\\x") && len(value) >= 4 {
			if raw, e := hex.DecodeString(value[2:4]); e == nil {
				b.Write(raw)
				value = value[4:]
				continue
			}
		}
		b.WriteByte(value[0])
		value = value[1:]
	}
	return b.String()
}
func (s *Service) scanNetwork() {
	s.networkMu.Lock()
	defer s.networkMu.Unlock()
	s.mu.Lock()
	enabled := s.cfg.WiFi && !s.cfg.Airplane
	busy := s.net.Busy
	s.mu.Unlock()
	if !enabled || s.simulate || busy {
		return
	}
	s.networkMessage("正在扫描", true)
	if _, e := s.wpa("scan"); e != nil {
		s.networkMessage("扫描失败，请稍后重试", false)
		return
	}
	time.Sleep(2 * time.Second)
	out, e := s.wpa("scan_results")
	if e != nil {
		s.networkMessage("读取无线列表失败", false)
		return
	}
	rows := parseScan(out)
	s.mu.Lock()
	s.net.Scan = rows
	s.net.Message = ""
	s.net.Busy = false
	s.mu.Unlock()
}
func (s *Service) connectNetwork(hexSSID, password string, saved bool) {
	s.networkMu.Lock()
	defer s.networkMu.Unlock()
	bytes, e := hex.DecodeString(hexSSID)
	if e != nil || len(bytes) == 0 || len(bytes) > 32 {
		s.networkMessage("无线名称无效", false)
		return
	}
	hexSSID = hex.EncodeToString(bytes)
	s.mu.Lock()
	enabled := s.cfg.WiFi && !s.cfg.Airplane
	busy := s.net.Busy
	s.mu.Unlock()
	if !enabled || busy || s.simulate {
		return
	}
	if password != "" && (len(password) < 8 || len(password) > 63 || strings.ContainsAny(password, "\x00\r\n")) {
		s.networkMessage("密码需为8至63字节", false)
		return
	}
	s.networkMessage("正在连接", true)
	index, created, e := s.prepareWiFiNetwork(hexSSID, password, saved)
	if e != nil {
		s.networkMessage(e.Error(), false)
		return
	}
	if _, e = strconv.Atoi(index); e != nil {
		s.networkMessage("无线接口未就绪", false)
		return
	}
	success := false
	defer func() {
		if !success {
			if created {
				_, _ = s.wpa("remove_network", index)
			}
			_, _ = s.wpa("enable_network", "all")
			_, _ = s.wpa("reassociate")
			s.refreshSavedNetworks()
		}
		password = ""
	}()
	if _, e = s.wpa("select_network", index); e != nil {
		s.networkMessage("选择无线网络失败", false)
		return
	}
	for attempt := 0; attempt < 25; attempt++ {
		s.waitNetwork(time.Second)
		s.mu.Lock()
		enabled = s.cfg.WiFi && !s.cfg.Airplane
		s.mu.Unlock()
		if !enabled {
			s.networkMessage("无线已关闭", false)
			return
		}
		out, _ := s.wpa("status")
		status := parseWPAStatus(out)
		if status["wpa_state"] == "COMPLETED" && status["id"] == index && status["ssid"] == string(bytes) {
			// Do not leave an earlier background DHCP process competing with this one.
			e = s.acquireNetworkLease()
			if e != nil {
				s.networkMessage("已认证，但未取得IP地址", false)
				return
			}
			success = true
			persistError := s.saveSelectedNetwork(index, hexSSID)
			s.mu.Lock()
			s.net.LeaseSSID = string(bytes)
			s.mu.Unlock()
			s.pollNetwork()
			if persistError != nil {
				s.networkMessage("已连接，但保存失败，请重试", false)
			} else {
				s.networkMessage("连接成功，已保存", false)
			}
			go s.refreshWeather()
			return
		}
	}
	s.networkMessage("连接失败，请检查密码与信号", false)
}
func sysKill(pid int) error {
	p, e := os.FindProcess(pid)
	if e != nil {
		return e
	}
	return p.Signal(os.Interrupt)
}

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"time"
)

const tailnetSocket = "/run/paperos/tailscaled.sock"
const tailnetMarker = "/etc/paperos/tailscale.enabled"

var tailnetIPv4 = netip.MustParsePrefix("100.64.0.0/10")

type TailnetConfig struct {
	Version               int
	Enabled, AllowReceive bool
}

type TailnetState struct {
	Installed, Connected, Busy bool
	Name, IP, Version, Message string
	Next                       time.Time
}

func isTailnetIPv4(value string) bool {
	ip, e := netip.ParseAddr(value)
	return e == nil && ip.Is4() && tailnetIPv4.Contains(ip)
}

// Read only the local node. Do not retain account identities, peer lists,
// authorization URLs or private daemon preferences in the UI snapshot.
func readTailnetStatus(socket string) (TailnetState, error) {
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", socket)
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 3 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	response, e := client.Get("http://local-tailscaled.sock/localapi/v0/status?peers=false")
	if e != nil {
		return TailnetState{}, e
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return TailnetState{}, errors.New("local Tailscale status unavailable")
	}
	body, e := io.ReadAll(io.LimitReader(response.Body, 1024*1024+1))
	if e != nil || len(body) > 1024*1024 {
		return TailnetState{}, errors.New("invalid Tailscale status size")
	}
	var raw struct {
		Version, BackendState string
		Health                []string
		Self                  *struct {
			HostName     string
			TailscaleIPs []string
			Online       bool
		}
	}
	if e = json.Unmarshal(body, &raw); e != nil {
		return TailnetState{}, e
	}
	state := TailnetState{Installed: true, Version: clean(raw.Version, 40)}
	if raw.Self != nil {
		state.Name = clean(raw.Self.HostName, 64)
		for _, ip := range raw.Self.TailscaleIPs {
			if isTailnetIPv4(ip) {
				state.IP = ip
				break
			}
		}
		state.Connected = raw.BackendState == "Running" && raw.Self.Online && state.IP != ""
	}
	switch {
	case state.Connected && len(raw.Health) == 0:
		state.Message = "已连接私有网络"
	case state.Connected:
		state.Message = "已连接，部分网络功能受限"
	case raw.BackendState == "NeedsLogin" || raw.BackendState == "NeedsMachineAuth":
		state.Message = "需要在电脑完成授权"
	case raw.BackendState == "Stopped":
		state.Message = "连接已停止，请重新开启连接"
	default:
		state.Message = "正在连接私有网络"
	}
	return state, nil
}

func (s *Service) loadTailnet() {
	if !s.simulate {
		_, binary := os.Stat("/usr/lib/paperos/tailscale/tailscaled")
		_, image := os.Stat("/mnt/us/paperos/tailnet.ext3")
		s.tailnet.Installed = binary == nil || image == nil
	}
	if s.cfg.Tailnet.Version == 0 {
		_, enabled := os.Stat(tailnetMarker)
		s.cfg.Tailnet = TailnetConfig{Version: 1, Enabled: !s.simulate && enabled == nil, AllowReceive: true}
	}
	if !s.cfg.Tailnet.Enabled {
		s.tailnet.Message = "已关闭"
	}
}

func setTailnetMarker(path string, enabled bool) error {
	if enabled {
		return atomicWrite(path, []byte("enabled\n"), 0600)
	}
	e := os.Remove(path)
	if os.IsNotExist(e) {
		return nil
	}
	return e
}

func switchTailnet(enabled bool) error {
	if e := setTailnetMarker(tailnetMarker, enabled); e != nil {
		return e
	}
	action := "stop"
	if enabled {
		action = "start"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	// The init script reuses the existing state; no logout, new login, ACL,
	// route, DNS, Serve or Funnel settings are changed here.
	return exec.CommandContext(ctx, "/etc/init.d/S46paperos-tailnet", action).Run()
}

func (s *Service) tailnetStatus() (TailnetState, error) {
	if s.tailnetReader != nil {
		return s.tailnetReader()
	}
	if s.simulate {
		s.mu.Lock()
		state := s.tailnet
		s.mu.Unlock()
		state.Connected = state.Installed && isTailnetIPv4(state.IP)
		state.Message = "已连接私有网络（模拟）"
		return state, nil
	}
	return readTailnetStatus(tailnetSocket)
}

func (s *Service) finishTailnet(state TailnetState, e error) {
	s.mu.Lock()
	if e != nil {
		s.tailnet.Connected = false
		s.tailnet.Message = "连接状态不可用，请稍后刷新"
	} else {
		s.tailnet.Installed = state.Installed
		s.tailnet.Connected = state.Connected && s.cfg.Tailnet.Enabled
		if state.IP != "" {
			s.tailnet.IP = state.IP
		}
		if state.Name != "" {
			s.tailnet.Name = state.Name
		}
		s.tailnet.Version = state.Version
		s.tailnet.Message = state.Message
	}
	if !s.cfg.Tailnet.Enabled {
		s.tailnet.Connected = false
		s.tailnet.Message = "已关闭"
	}
	s.tailnet.Busy = false
	s.tailnet.Next = time.Now().Add(15 * time.Second)
	s.mu.Unlock()
	s.reconcileReceiver()
	s.publish()
}

func (s *Service) pollTailnet(force bool) {
	s.mu.Lock()
	if s.tailnet.Busy || s.sleep.Busy || !s.cfg.Tailnet.Enabled || (!force && time.Now().Before(s.tailnet.Next)) {
		s.mu.Unlock()
		return
	}
	s.tailnet.Busy = true
	s.mu.Unlock()
	go func() { state, e := s.tailnetStatus(); s.finishTailnet(state, e) }()
}

func (s *Service) applyTailnet() {
	s.networkMu.Lock()
	defer s.networkMu.Unlock()
	s.mu.Lock()
	enabled := s.cfg.Tailnet.Enabled
	s.mu.Unlock()
	var e error
	if s.tailnetSwitch != nil {
		e = s.tailnetSwitch(enabled)
	} else if !s.simulate {
		e = switchTailnet(enabled)
	}
	var state TailnetState
	if e == nil && enabled {
		state, e = s.tailnetStatus()
	} else {
		s.mu.Lock()
		state = s.tailnet
		s.mu.Unlock()
	}
	s.finishTailnet(state, e)
}

func (s *Service) commandTailnetLocked(v url.Values) error {
	if s.tailnet.Busy {
		return errors.New("正在更新连接状态，请稍后重试")
	}
	if v.Get("cmd") == "tailnet-refresh" {
		if !s.cfg.Tailnet.Enabled {
			return nil
		}
		go s.pollTailnet(true)
		return nil
	}
	if v.Get("enabled") != "true" && v.Get("enabled") != "false" {
		return errors.New("开关值无效")
	}
	enabled := v.Get("enabled") == "true"
	previous := s.cfg.Tailnet
	if v.Get("cmd") == "tailnet-enable" {
		if enabled && !s.tailnet.Installed {
			return errors.New("尚未安装 Tailscale 客户端")
		}
		s.cfg.Tailnet.Enabled = enabled
	} else {
		s.cfg.Tailnet.AllowReceive = enabled
	}
	if e := s.saveLocked(); e != nil {
		s.cfg.Tailnet = previous
		return e
	}
	if !s.cfg.Tailnet.Enabled || !s.cfg.Tailnet.AllowReceive {
		s.rejectTailnetPendingLocked()
	}
	go s.reconcileReceiver()
	if v.Get("cmd") == "tailnet-enable" {
		s.tailnet.Busy = true
		s.tailnet.Message = "正在调整私网连接"
		go s.applyTailnet()
	}
	return nil
}

func (s *Service) tailnetConnectedLocked() bool {
	return s.cfg.Tailnet.Enabled && s.tailnet.Connected && s.cfg.WiFi && !s.cfg.Airplane && s.net.Connected
}

func (s *Service) publishTailnetLocked(b *strings.Builder) {
	fmt.Fprintf(b, "tailnet\t%t\t%t\t%t\t%t\t%t\t%s\t%s\t%s\t%s\t%t\n",
		s.tailnet.Installed, s.cfg.Tailnet.Enabled, s.cfg.Tailnet.AllowReceive, s.tailnetConnectedLocked(), s.tailnet.Busy,
		field(s.tailnet.Name), field(s.tailnet.IP), field(s.tailnet.Version), field(s.tailnet.Message), s.receiverTailnet != nil)
}

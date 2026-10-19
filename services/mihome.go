package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Xiaomi's official integration runs in Home Assistant. PaperOS consumes only
// the user-selected states; this client never calls appliance control services.
type MiHomeBinding struct{ Entity, Label, Room, Kind string }
type MiHomeConfig struct {
	Version                                int
	BaseURL, Token, RefreshToken, ClientID string
	ExpiresAt                              int64
	Proxy, Name                            string
	Items                                  []MiHomeBinding
}
type MiHomeValue struct {
	Entity, Label, Room, Kind, Value, Unit string
	Available, Stale                       bool
	At                                     int64
}
type MiHomeCache struct {
	ID    string
	At    int64
	Items []MiHomeValue
}
type MiHomeState struct {
	Config           MiHomeConfig
	Configured, Busy bool
	Cache            MiHomeCache
	Message          string
	Revision, Run    uint64
	Next             time.Time
	Cancel           context.CancelFunc
}

var homeEntity = regexp.MustCompile(`^(sensor|binary_sensor|light|switch|fan|climate)\.[a-z0-9_]{1,128}$`)

func validateMiHome(c *MiHomeConfig) error {
	u, e := url.Parse(c.BaseURL)
	if e != nil || len(c.BaseURL) > 512 || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return errors.New("家庭中枢地址无效")
	}
	c.BaseURL = strings.TrimRight(c.BaseURL, "/")
	if (c.Token == "" && c.RefreshToken == "") || len(c.Token) > 4096 || len(c.RefreshToken) > 4096 || strings.ContainsAny(c.Token, "\r\n") || strings.ContainsAny(c.RefreshToken, "\r\n") {
		return errors.New("缺少有效的中枢授权")
	}
	if c.RefreshToken != "" {
		id, e := url.Parse(c.ClientID)
		if e != nil || id.Host == "" || (id.Scheme != "http" && id.Scheme != "https") || len(c.ClientID) > 512 {
			return errors.New("授权应用标识无效")
		}
	}
	if c.Proxy != "" {
		p, e := url.Parse(c.Proxy)
		if e != nil || (p.Scheme != "http" && p.Scheme != "socks5") || (p.Hostname() != "127.0.0.1" && p.Hostname() != "localhost" && p.Hostname() != "::1") || p.User != nil || p.RawQuery != "" || p.Fragment != "" {
			return errors.New("远程家庭代理应为本机 Tailscale 代理")
		}
	}
	if len(c.Items) < 1 || len(c.Items) > 12 {
		return errors.New("请选择1至12项家庭指标或设备状态")
	}
	seen := map[string]bool{}
	for i := range c.Items {
		item := &c.Items[i]
		if !homeEntity.MatchString(item.Entity) || seen[item.Entity] {
			return errors.New("家庭设备标识无效或重复")
		}
		seen[item.Entity] = true
		switch item.Kind {
		case "temperature", "humidity", "pm25", "co2", "metric", "state":
		default:
			return errors.New("家庭指标类型无效")
		}
		item.Label = clean(item.Label, 32)
		item.Room = clean(item.Room, 24)
		if item.Label == "" {
			item.Label = item.Entity
		}
	}
	c.Version = 1
	c.Name = clean(c.Name, 32)
	if c.Name == "" {
		c.Name = "家中"
	}
	return nil
}
func miHomeID(c MiHomeConfig) string {
	if c.RefreshToken != "" {
		c.Token = ""
	}
	c.ExpiresAt = 0
	data, _ := json.Marshal(c)
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}
func (s *Service) loadMiHome() {
	s.mihome.Revision = uint64(uint32(time.Now().UnixNano()) & 0x7fffffff)
	data, e := os.ReadFile(filepath.Join(s.root, "mihome.json"))
	if os.IsNotExist(e) {
		s.mihome.Message = "请在电脑端绑定家庭中枢"
		return
	}
	var c MiHomeConfig
	if e != nil || len(data) > 32768 || json.Unmarshal(data, &c) != nil || validateMiHome(&c) != nil {
		s.mihome.Message = "家庭配置需要重新绑定"
		return
	}
	s.mihome.Config = c
	s.mihome.Configured = true
	data, e = os.ReadFile(filepath.Join(s.root, "mihome-cache.json"))
	var cache MiHomeCache
	if e == nil && len(data) <= 32768 && json.Unmarshal(data, &cache) == nil && cache.ID == miHomeID(c) && len(cache.Items) <= 12 {
		for i := range cache.Items {
			cache.Items[i].Stale = true
		}
		s.mihome.Cache = cache
	}
	s.mihome.Message = "等待联网更新"
	s.publishMiHomeHistoryLocked()
}
func miHomeClient(c MiHomeConfig) *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	if c.Proxy != "" {
		proxy, _ := url.Parse(c.Proxy)
		if proxy.Scheme == "http" {
			// CONNECT keeps HA's original HTTP request intact. A forwarding
			// proxy can add X-Forwarded-For, which HA correctly rejects unless
			// explicitly configured to trust that proxy.
			transport.DialContext = homeProxyDial(proxy)
		} else {
			transport.Proxy = http.ProxyURL(proxy)
		}
	}
	return &http.Client{Transport: transport, Timeout: 12 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

type homeProxyConn struct {
	net.Conn
	reader *bufio.Reader
}

func (c *homeProxyConn) Read(p []byte) (int, error) { return c.reader.Read(p) }

func homeProxyDial(proxy *url.URL) func(context.Context, string, string) (net.Conn, error) {
	port := proxy.Port()
	if port == "" {
		port = "80"
	}
	endpoint := net.JoinHostPort(proxy.Hostname(), port)
	return func(ctx context.Context, network, address string) (net.Conn, error) {
		conn, e := (&net.Dialer{Timeout: 12 * time.Second}).DialContext(ctx, "tcp", endpoint)
		if e != nil {
			return nil, e
		}
		stop := context.AfterFunc(ctx, func() { _ = conn.Close() })
		defer stop()
		deadline := time.Now().Add(12 * time.Second)
		if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
			deadline = d
		}
		_ = conn.SetDeadline(deadline)
		request := &http.Request{Method: http.MethodConnect, URL: &url.URL{Opaque: address}, Host: address}
		if e = request.Write(conn); e != nil {
			_ = conn.Close()
			return nil, e
		}
		reader := bufio.NewReader(conn)
		response, e := http.ReadResponse(reader, request)
		if e != nil {
			_ = conn.Close()
			return nil, e
		}
		if response.StatusCode != http.StatusOK {
			_ = conn.Close()
			return nil, errors.New("家庭代理无法建立连接")
		}
		_ = conn.SetDeadline(time.Time{})
		return &homeProxyConn{Conn: conn, reader: reader}, nil
	}
}
func refreshMiHomeToken(ctx context.Context, client *http.Client, c *MiHomeConfig) error {
	if c.RefreshToken == "" || (c.Token != "" && c.ExpiresAt > time.Now().Unix()+60) {
		return nil
	}
	values := url.Values{"grant_type": {"refresh_token"}, "refresh_token": {c.RefreshToken}, "client_id": {c.ClientID}}
	request, e := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/auth/token", strings.NewReader(values.Encode()))
	if e != nil {
		return e
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	response, e := client.Do(request)
	if e != nil {
		return errors.New("家庭中枢暂不可达")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return errors.New("中枢授权已失效，请在电脑重新连接")
	}
	var token struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int64  `json:"expires_in"`
	}
	if json.NewDecoder(io.LimitReader(response.Body, 16384)).Decode(&token) != nil || token.AccessToken == "" || len(token.AccessToken) > 4096 || token.ExpiresIn < 1 || token.ExpiresIn > 86400 {
		return errors.New("中枢授权回复无效")
	}
	c.Token = token.AccessToken
	c.ExpiresAt = time.Now().Unix() + token.ExpiresIn
	return nil
}
func fetchMiHomeValue(ctx context.Context, client *http.Client, c MiHomeConfig, binding MiHomeBinding) (MiHomeValue, error) {
	item := MiHomeValue{Entity: binding.Entity, Label: binding.Label, Room: binding.Room, Kind: binding.Kind}
	request, e := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/states/"+url.PathEscape(binding.Entity), nil)
	if e != nil {
		return item, e
	}
	request.Header.Set("Authorization", "Bearer "+c.Token)
	request.Header.Set("Accept", "application/json")
	response, e := client.Do(request)
	if e != nil {
		return item, errors.New("家庭中枢暂不可达")
	}
	defer response.Body.Close()
	if response.StatusCode == 401 || response.StatusCode == 403 {
		return item, errors.New("中枢授权已失效，请在电脑重新连接")
	}
	if response.StatusCode == 404 {
		item.Value = "未找到设备"
		item.At = time.Now().Unix()
		return item, nil
	}
	if response.StatusCode != 200 {
		return item, errors.New("家庭中枢暂不可达")
	}
	var raw struct {
		Entity     string `json:"entity_id"`
		State      string `json:"state"`
		Attributes struct {
			Unit string `json:"unit_of_measurement"`
		} `json:"attributes"`
	}
	data, e := io.ReadAll(io.LimitReader(response.Body, 65537))
	if e != nil || len(data) > 65536 || json.Unmarshal(data, &raw) != nil || raw.Entity != binding.Entity {
		return item, errors.New("家庭设备回复无效")
	}
	item.At = time.Now().Unix()
	item.Unit = clean(raw.Attributes.Unit, 16)
	if raw.State == "unavailable" || raw.State == "unknown" || raw.State == "" {
		item.Value = "设备离线"
		return item, nil
	}
	item.Available = true
	if binding.Kind != "state" {
		n, e := strconv.ParseFloat(raw.State, 64)
		if e != nil || math.IsNaN(n) || math.IsInf(n, 0) || (binding.Kind == "humidity" && (n < 0 || n > 100)) {
			item.Available = false
			item.Value = "读数无效"
			return item, nil
		}
		precision := 1
		if binding.Kind == "co2" || binding.Kind == "pm25" || binding.Kind == "humidity" {
			precision = 0
		}
		item.Value = strconv.FormatFloat(n, 'f', precision, 64)
	} else {
		names := map[string]string{"on": "开启", "off": "关闭", "open": "打开", "closed": "关闭", "home": "在家", "not_home": "离家", "heat": "制热", "cool": "制冷", "auto": "自动", "idle": "待机", "dry": "除湿", "fan_only": "送风"}
		item.Value = names[raw.State]
		if item.Value == "" {
			item.Value = clean(raw.State, 48)
		}
	}
	return item, nil
}
func (s *Service) pollMiHome(force bool) {
	s.mu.Lock()
	if !s.simulate {
		info, e := os.Stat(filepath.Join(s.apps, "org.paperos.mihome", "manifest.conf"))
		if e != nil || !info.Mode().IsRegular() {
			s.mu.Unlock()
			return
		}
	}
	if !s.mihome.Configured || s.mihome.Busy || s.sleep.Busy || !s.net.Connected || s.cfg.Airplane || (!force && time.Now().Before(s.mihome.Next)) {
		s.mu.Unlock()
		return
	}
	s.mihome.Busy = true
	s.mihome.Run++
	run := s.mihome.Run
	c := s.mihome.Config
	old := s.mihome.Cache
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	s.mihome.Cancel = cancel
	s.mu.Unlock()
	s.publish()
	go func() {
		defer cancel()
		client := miHomeClient(c)
		defer client.CloseIdleConnections()
		failure := refreshMiHomeToken(ctx, client, &c)
		cache := MiHomeCache{ID: miHomeID(c)}
		fresh := 0
		if failure == nil {
			for _, binding := range c.Items {
				item, e := fetchMiHomeValue(ctx, client, c, binding)
				if e != nil {
					failure = e
					for _, previous := range old.Items {
						if previous.Entity == binding.Entity {
							item = previous
							break
						}
					}
					item.Stale = true
				} else {
					fresh++
				}
				cache.Items = append(cache.Items, item)
			}
		}
		s.mu.Lock()
		defer func() { s.mu.Unlock(); s.publish() }()
		if run != s.mihome.Run || miHomeID(s.mihome.Config) != cache.ID {
			return
		}
		s.mihome.Busy = false
		s.mihome.Cancel = nil
		s.mihome.Next = time.Now().Add(2 * time.Minute)
		if c.Token != s.mihome.Config.Token || c.ExpiresAt != s.mihome.Config.ExpiresAt {
			s.mihome.Config = c
			data, _ := json.Marshal(c)
			if atomicWrite(filepath.Join(s.root, "mihome.json"), data, 0600) != nil {
				s.mihome.Message = "授权保存失败，请稍后重试"
				return
			}
		}
		if fresh > 0 {
			cache.At = time.Now().Unix()
			s.mihome.Cache = cache
		} else {
			for i := range s.mihome.Cache.Items {
				s.mihome.Cache.Items[i].Stale = true
			}
		}
		s.mihome.Message = "已更新"
		if failure != nil {
			s.mihome.Message = failure.Error() + " · 显示已有缓存"
		}
		if fresh > 0 {
			data, _ := json.Marshal(cache)
			if atomicWrite(filepath.Join(s.root, "mihome-cache.json"), data, 0600) != nil {
				s.mihome.Message = "读数已更新，缓存保存失败"
			}
		}
		s.mihome.Revision++
		s.publishMiHomeHistoryLocked()
	}()
}
func (s *Service) publishMiHomeHistoryLocked() {
	if s.run == "" {
		return
	}
	var b strings.Builder
	fmt.Fprintf(&b, "paperos-mihome-v1\t%d\n", s.mihome.Revision)
	for _, item := range s.mihome.Cache.Items {
		fmt.Fprintf(&b, "item\t%s\t%s\t%s\t%s\t%s\t%t\t%t\t%d\t%s\n", field(item.Kind), field(item.Label), field(item.Room), field(item.Value), field(item.Unit), item.Available, item.Stale, item.At, field(item.Entity))
	}
	_ = atomicWrite(filepath.Join(s.run, "mihome.tsv"), []byte(b.String()), 0644)
}
func (s *Service) publishMiHomeLocked(b *strings.Builder) {
	fmt.Fprintf(b, "mihome\t%t\t%t\t%d\t%s\t%s\t%d\t%s\n", s.mihome.Configured, s.mihome.Busy, s.mihome.Cache.At, field(s.mihome.Config.Name), field(filepath.Join(s.run, "mihome.tsv")), s.mihome.Revision, field(s.mihome.Message))
}
func (s *Service) handleMiHomeConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "POST required", 405)
		return
	}
	data, e := io.ReadAll(io.LimitReader(r.Body, 32769))
	var c MiHomeConfig
	if e != nil || len(data) > 32768 || json.Unmarshal(data, &c) != nil {
		http.Error(w, "家庭配置格式无效", 400)
		return
	}
	if e = validateMiHome(&c); e != nil {
		http.Error(w, e.Error(), 400)
		return
	}
	s.mu.Lock()
	if s.sleep.Busy {
		s.cancelSleepLocked()
	}
	encoded, _ := json.Marshal(c)
	e = atomicWrite(filepath.Join(s.root, "mihome.json"), encoded, 0600)
	if e == nil {
		if s.mihome.Cancel != nil {
			s.mihome.Cancel()
		}
		s.mihome.Run++
		s.mihome.Config = c
		s.mihome.Configured = true
		s.mihome.Busy = false
		s.mihome.Cache = MiHomeCache{}
		s.mihome.Revision++
		s.mihome.Next = time.Time{}
		s.mihome.Message = "等待联网更新"
		s.publishMiHomeHistoryLocked()
	}
	s.mu.Unlock()
	if e != nil {
		http.Error(w, "无法保存家庭配置", 500)
		return
	}
	s.publish()
	s.pollMiHome(true)
	fmt.Fprintln(w, "家庭显示配置已保存")
}
func importMiHomeCLI(run string) error {
	data, e := io.ReadAll(io.LimitReader(os.Stdin, 32769))
	if e != nil || len(data) > 32768 {
		return errors.New("家庭配置过大")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(run, "services.sock"))
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
	response, e := client.Post("http://paperos/mihome/config", "application/json", bytes.NewReader(data))
	if e != nil {
		return errors.New("家庭配置服务未连接")
	}
	defer response.Body.Close()
	answer, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
	if response.StatusCode != 200 {
		return errors.New(string(answer))
	}
	fmt.Print(string(answer))
	return nil
}

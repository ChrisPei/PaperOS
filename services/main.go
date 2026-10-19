// PaperOS background services. The touchscreen remains owned by the native UI.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

var china = time.FixedZone("CST", 8*3600)

type Alarm struct {
	ID, Hour, Minute, Days int
	Enabled                bool
	Label                  string
	Next                   int64
}
type Timer struct {
	State               string
	Duration, Remaining int
	BootID              string
	BootDeadline        float64
	WallDeadline        int64
}
type Alert struct {
	ID, Kind, Label string
	Duration        int
}
type Config struct {
	Version         int
	WiFi, Airplane  bool
	Alarms          []Alarm
	Timer, Snooze   Timer
	SnoozeAlert     Alert
	Active          *Alert
	Queue           []Alert
	Weather         Weather
	WeatherLocation WeatherLocation
	Clock           ClockConfig
	Lock            LockConfig
	Sleep           SleepConfig
	Tailnet         TailnetConfig
}
type Network struct {
	Connected         bool
	IP, SSID, Message string
	Busy              bool
	Scan              []WiFi
	Saved             []SavedWiFi
	LeaseSSID         string
	LeaseBusy         bool
}
type Service struct {
	networkMu                 sync.Mutex
	wifiControl               func(...string) (string, error)
	dhcpRunner                func() error
	wifiAddress               func() string
	networkWait               func(time.Duration)
	mu                        sync.Mutex
	cfg                       Config
	net                       Network
	root, run, apps, packages string
	simulate                  bool
	httpClient                *http.Client
	weatherURL                string
	weatherBusy               bool
	weatherRun                uint64
	weatherCancel             context.CancelFunc
	geocodingURL              string
	locationSearch            LocationSearch
	locationSearchRun         uint64
	locationSearchCancel      context.CancelFunc
	receiveUntil              time.Time
	pending                   *Transfer
	uploading                 bool
	transfers                 map[string]*Transfer
	receiver                  *http.Server
	receiverIP                string
	receiverTailnet           *http.Server
	certificate               []byte
	message                   string
	clockBusy, clockConnected bool
	clockMessage              string
	clockRun                  uint64
	clockNext                 time.Time
	clockCancel               context.CancelFunc
	clockQuery                func(context.Context) (ClockSample, error)
	clockSetter               func(time.Time) error
	clockRTC                  func() error
	lock                      LockState
	spotlight                 SpotlightCache
	spotlightBusy             bool
	spotlightNext             time.Time
	spotlightMessage          string
	galleryPublished          uint64
	powerLastSequence         uint64
	powerLastAt               float64
	sleep                     SleepState
	sleepRunner               func(uint64, int64) (SleepResult, error)
	battery                   BatteryState
	batteryReader             func() (BatteryReading, error)
	supply                    ExternalPowerState
	supplyReader              func() (bool, error)
	mihome                    MiHomeState
	tailnet                   TailnetState
	tailnetReader             func() (TailnetState, error)
	tailnetSwitch             func(bool) error
	store                     *StoreState
	storeClient               *http.Client
	storeClientOnce           sync.Once
	storeInstaller            string
}

func clean(s string, limit int) string {
	s = strings.Map(func(r rune) rune {
		if r < 32 || r == 127 {
			return ' '
		}
		return r
	}, s)
	r := []rune(s)
	if len(r) > limit {
		r = r[:limit]
	}
	return string(r)
}
func atomicWrite(path string, data []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".paperos-")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if err = f.Chmod(mode); err == nil {
		_, err = f.Write(data)
	}
	if err == nil {
		err = f.Sync()
	}
	if e := f.Close(); err == nil {
		err = e
	}
	if err == nil {
		err = os.Rename(name, path)
	}
	if err == nil {
		if d, e := os.Open(filepath.Dir(path)); e == nil {
			err = d.Sync()
			d.Close()
		}
	}
	return err
}
func (s *Service) saveLocked() error {
	s.cfg.Version = 1
	data, err := json.MarshalIndent(s.cfg, "", "  ")
	if err != nil {
		return err
	}
	return atomicWrite(filepath.Join(s.root, "state.json"), append(data, '\n'), 0600)
}
func uptime() float64 {
	data, _ := os.ReadFile("/proc/uptime")
	fields := strings.Fields(string(data))
	if len(fields) == 0 {
		return float64(time.Now().Unix())
	}
	n, _ := strconv.ParseFloat(fields[0], 64)
	return n
}
func bootID() string {
	data, _ := os.ReadFile("/proc/sys/kernel/random/boot_id")
	return strings.TrimSpace(string(data))
}
func nextAlarm(a Alarm, now time.Time) int64 {
	local := now.In(china)
	for offset := 0; offset < 8; offset++ {
		day := local.AddDate(0, 0, offset)
		at := time.Date(day.Year(), day.Month(), day.Day(), a.Hour, a.Minute, 0, 0, china)
		bit := (int(day.Weekday()) + 6) % 7
		if at.After(now) && (a.Days == 0 || a.Days&(1<<bit) != 0) {
			return at.Unix()
		}
	}
	return 0
}
func timerRemaining(t *Timer, now time.Time, boot float64, id string) int {
	if t.State != "running" {
		return t.Remaining
	}
	if t.BootID != id {
		t.BootID = id
		t.BootDeadline = boot + float64(t.WallDeadline-now.Unix())
	}
	remaining := int(t.BootDeadline - boot + 0.999)
	if remaining < 0 {
		return 0
	}
	return remaining
}
func newTimer(seconds int, now time.Time, boot float64, id string) Timer {
	return Timer{State: "running", Duration: seconds, Remaining: seconds, BootID: id, BootDeadline: boot + float64(seconds), WallDeadline: now.Unix() + int64(seconds)}
}
func (s *Service) queueLocked(a Alert) {
	if s.cfg.Active == nil {
		s.cfg.Active = &a
	} else if len(s.cfg.Queue) < 16 {
		s.cfg.Queue = append(s.cfg.Queue, a)
	}
}
func (s *Service) tick(now time.Time, boot float64, id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	changed := false
	for i := range s.cfg.Alarms {
		a := &s.cfg.Alarms[i]
		if !a.Enabled {
			continue
		}
		if a.Next == 0 {
			a.Next = nextAlarm(*a, now)
			changed = true
		}
		if a.Next > 0 && now.Unix() >= a.Next {
			if now.Unix()-a.Next < 24*3600 {
				s.queueLocked(Alert{ID: fmt.Sprintf("alarm-%d-%d", a.ID, a.Next), Kind: "alarm", Label: a.Label})
			}
			if a.Days == 0 {
				a.Enabled = false
				a.Next = 0
			} else {
				a.Next = nextAlarm(*a, now)
			}
			changed = true
		}
	}
	for i, t := range []*Timer{&s.cfg.Timer, &s.cfg.Snooze} {
		if t.State == "running" && timerRemaining(t, now, boot, id) == 0 {
			t.State = "finished"
			t.Remaining = 0
			a := Alert{ID: fmt.Sprintf("timer-%d", t.WallDeadline), Kind: "timer", Label: "倒计时结束", Duration: t.Duration}
			if i == 1 {
				a = s.cfg.SnoozeAlert
				a.ID += "-snooze-" + strconv.FormatInt(t.WallDeadline, 10)
			}
			s.queueLocked(a)
			changed = true
		}
	}
	if changed {
		if err := s.saveLocked(); err != nil {
			s.message = "提醒保存失败"
			log.Printf("persist reminder: %v", err)
		}
	}
	return changed
}
func field(v string) string {
	v = clean(v, 160)
	if v == "" {
		return "-"
	}
	return v
}
func (s *Service) publish() {
	s.mu.Lock()
	defer s.mu.Unlock()
	var b strings.Builder
	b.WriteString("paperos-services-v1\n")
	fmt.Fprintf(&b, "net\t%t\t%t\t%t\t%s\t%s\t%t\t%s\n", s.cfg.WiFi, s.cfg.Airplane, s.net.Connected, field(s.net.IP), field(s.net.SSID), s.net.Busy, field(s.net.Message))
	for _, a := range s.cfg.Alarms {
		fmt.Fprintf(&b, "alarm\t%d\t%d\t%d\t%d\t%t\t%s\t%d\n", a.ID, a.Hour, a.Minute, a.Days, a.Enabled, field(a.Label), a.Next)
	}
	t := s.cfg.Timer
	fmt.Fprintf(&b, "timer\t%s\t%d\t%d\n", field(t.State), t.Duration, timerRemaining(&t, time.Now(), uptime(), bootID()))
	if a := s.cfg.Active; a != nil {
		fmt.Fprintf(&b, "alert\t%s\t%s\t%s\t%d\n", a.ID, a.Kind, field(a.Label), a.Duration)
	}
	for i, w := range s.net.Scan {
		fmt.Fprintf(&b, "wifi\t%d\t%d\t%s\t%s\t%s\n", i, w.Level, field(w.Security), field(w.SSID), w.Hex)
	}
	for _, w := range s.net.Saved {
		level, available := 0, false
		for _, scan := range s.net.Scan {
			if scan.Hex == w.Hex {
				level, available = scan.Level, true
				break
			}
		}
		fmt.Fprintf(&b, "wifi-saved\t%d\t%s\t%s\t%t\t%t\t%d\n", w.ID, field(w.SSID), w.Hex, w.Current, available, level)
	}
	w := &s.cfg.Weather
	fmt.Fprintf(&b, "weather\t%d\t%g\t%d\t%g\t%g\t%s\n", w.Fetched, w.Temperature, w.Code, w.High, w.Low, field(w.Message))
	s.publishWeatherLocationLocked(&b)
	for _, h := range w.Hours {
		fmt.Fprintf(&b, "hour\t%d\t%g\t%d\t%g\t%g\n", h.Time, h.Temperature, h.Code, h.Rain, h.Wind)
	}
	fmt.Fprintf(&b, "receive\t%t\t8765\n", s.receiveUntil.After(time.Now()))
	s.publishTailnetLocked(&b)
	fmt.Fprintf(&b, "clock\t%t\t%t\t%d\t%s\t%s\n", s.cfg.Clock.Automatic, s.clockBusy, s.cfg.Clock.LastSync, field(s.cfg.Clock.Source), field(s.clockMessage))
	s.publishLockLocked(&b)
	s.publishSleepLocked(&b)
	s.publishBatteryLocked(&b)
	s.publishMiHomeLocked(&b)
	s.publishStoreLocked(&b)
	if p := s.pending; p != nil && p.Phase == "pending" {
		fmt.Fprintf(&b, "transfer\t%s\t%s\t%s\t%s\t%s\t%s\n", p.ID, field(p.Name), field(p.Version), field(p.Peer), p.Code, p.Digest)
	}
	fmt.Fprintf(&b, "message\t%s\n", field(s.message))
	if err := atomicWrite(filepath.Join(s.run, "state.tsv"), []byte(b.String()), 0644); err != nil {
		log.Printf("snapshot: %v", err)
	}
}
func integer(v url.Values, key string, min, max int) (int, error) {
	n, err := strconv.Atoi(v.Get(key))
	if err != nil || n < min || n > max {
		return 0, fmt.Errorf("invalid %s", key)
	}
	return n, nil
}
func (s *Service) command(v url.Values) error {
	name := v.Get("cmd")
	now, boot, id := time.Now(), uptime(), bootID()
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.sleep.Busy && name != "lock-activity" {
		s.cancelSleepLocked()
	}
	if handled, err := s.sleepCommandLocked(v, boot); handled {
		return err
	}
	if handled, err := s.lockCommandLocked(v, boot); handled {
		return err
	}
	if handled, err := s.weatherLocationCommandLocked(v); handled {
		return err
	}
	if handled, err := s.storeCommandLocked(v); handled {
		return err
	}
	s.message = ""
	switch name {
	case "alarm-save":
		ident, _ := strconv.Atoi(v.Get("id"))
		h, e := integer(v, "hour", 0, 23)
		if e != nil {
			return e
		}
		m, e := integer(v, "minute", 0, 59)
		if e != nil {
			return e
		}
		d, e := integer(v, "days", 0, 127)
		if e != nil {
			return e
		}
		label := clean(v.Get("label"), 40)
		if label == "" {
			label = "闹钟"
		}
		found := -1
		maxID := 0
		for i, a := range s.cfg.Alarms {
			if a.ID == ident {
				found = i
			}
			if a.ID > maxID {
				maxID = a.ID
			}
		}
		if found < 0 {
			if len(s.cfg.Alarms) >= 8 {
				return errors.New("最多可设置8个闹钟")
			}
			ident = maxID + 1
			s.cfg.Alarms = append(s.cfg.Alarms, Alarm{})
			found = len(s.cfg.Alarms) - 1
		}
		a := Alarm{ID: ident, Hour: h, Minute: m, Days: d, Enabled: v.Get("enabled") != "false", Label: label}
		if a.Enabled {
			a.Next = nextAlarm(a, now)
		}
		s.cfg.Alarms[found] = a
	case "alarm-toggle", "alarm-remove":
		ident, e := integer(v, "id", 1, 1<<30)
		if e != nil {
			return e
		}
		found := false
		for i := range s.cfg.Alarms {
			a := &s.cfg.Alarms[i]
			if a.ID != ident {
				continue
			}
			found = true
			if name == "alarm-remove" {
				s.cfg.Alarms = append(s.cfg.Alarms[:i], s.cfg.Alarms[i+1:]...)
			} else {
				a.Enabled = !a.Enabled
				a.Next = 0
				if a.Enabled {
					a.Next = nextAlarm(*a, now)
				}
			}
			break
		}
		if !found {
			return errors.New("闹钟不存在")
		}
	case "timer-start":
		n, e := integer(v, "seconds", 1, 7*24*3600)
		if e != nil {
			return e
		}
		s.cfg.Timer = newTimer(n, now, boot, id)
	case "timer-pause":
		t := &s.cfg.Timer
		if t.State != "running" {
			return errors.New("计时未运行")
		}
		t.Remaining = timerRemaining(t, now, boot, id)
		t.State = "paused"
	case "timer-resume":
		t := s.cfg.Timer
		if t.State != "paused" || t.Remaining <= 0 {
			return errors.New("没有暂停的计时")
		}
		s.cfg.Timer = newTimer(t.Remaining, now, boot, id)
		s.cfg.Timer.Duration = t.Duration
	case "timer-cancel":
		s.cfg.Timer = Timer{}
	case "alarm-disarm":
		for i := range s.cfg.Alarms {
			s.cfg.Alarms[i].Enabled = false
			s.cfg.Alarms[i].Next = 0
		}
		s.cfg.Timer = Timer{}
		s.cfg.Snooze = Timer{}
		s.cfg.Active = nil
		s.cfg.Queue = nil
	case "alert-stop", "alert-snooze":
		if s.cfg.Active == nil || s.cfg.Active.ID != v.Get("id") {
			return errors.New("这条提醒已经结束")
		}
		if name == "alert-snooze" {
			s.cfg.Snooze = newTimer(300, now, boot, id)
			s.cfg.SnoozeAlert = *s.cfg.Active
		}
		s.cfg.Active = nil
		if len(s.cfg.Queue) > 0 {
			a := s.cfg.Queue[0]
			s.cfg.Active = &a
			s.cfg.Queue = s.cfg.Queue[1:]
		}
	case "time-set":
		if s.cfg.Clock.Automatic {
			return errors.New("请先关闭自动对时")
		}
		at, e := time.ParseInLocation("2006-01-02 15:04", v.Get("value"), china)
		if e != nil || at.Year() < 2000 || at.Year() > 2100 {
			return errors.New("日期或时间无效")
		}
		s.cancelClockLocked()
		rtc, e := s.applyClockLocked(at)
		if e != nil {
			return e
		}
		s.cfg.Clock.LastSync, s.cfg.Clock.Source = 0, ""
		s.clockMessage = "手动时间已保存"
		if !rtc {
			s.message = "系统时间已设置；硬件时钟写入未确认"
		}
	case "time-auto":
		s.cfg.Clock.Automatic = v.Get("enabled") == "true"
		if !s.cfg.Clock.Automatic {
			s.cancelClockLocked()
			s.clockMessage = ""
		} else {
			s.clockNext = time.Time{}
			if e := s.startClockSyncLocked(); e != nil {
				s.clockMessage = e.Error()
			}
		}
	case "time-sync":
		if e := s.startClockSyncLocked(); e != nil {
			return e
		}
	case "network-enable", "airplane":
		on := v.Get("enabled") == "true"
		if name == "airplane" {
			s.cfg.Airplane = on
		} else {
			s.cfg.WiFi = on
			if on {
				s.cfg.Airplane = false
			}
		}
		if !s.cfg.WiFi || s.cfg.Airplane {
			s.cancelClockLocked()
		}
		go s.applyNetwork()
	case "network-scan":
		go s.scanNetwork()
	case "network-connect":
		hexSSID := v.Get("ssid")
		pass := v.Get("password")
		go s.connectNetwork(hexSSID, pass, v.Get("saved") == "true")
	case "network-forget":
		go s.forgetNetwork(v.Get("ssid"))
	case "receive-enable":
		if v.Get("enabled") == "true" {
			if !s.net.Connected || s.cfg.Airplane {
				return errors.New("请先连接 Wi-Fi")
			}
			s.receiveUntil = now.Add(10 * time.Minute)
		} else {
			s.receiveUntil = time.Time{}
			if s.pending != nil {
				s.pending.Phase = "rejected"
				s.pending = nil
			}
		}
		go s.reconcileReceiver()
	case "tailnet-enable", "tailnet-receive", "tailnet-refresh":
		return s.commandTailnetLocked(v)
	case "receive-approve", "receive-reject":
		p := s.pending
		if p == nil || p.ID != v.Get("id") {
			return errors.New("接收请求已失效")
		}
		s.pending = nil
		if name == "receive-reject" {
			p.Phase = "rejected"
			go os.RemoveAll(p.Directory)
		} else {
			p.Phase = "accepting"
			go s.acceptTransfer(p)
		}
	case "weather-refresh":
		go s.refreshWeather(true)
	case "mihome-refresh":
		go s.pollMiHome(true)
	default:
		return errors.New("不支持的操作")
	}
	return s.saveLocked()
}
func (s *Service) handler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/mihome/config" {
		s.handleMiHomeConfig(w, r)
		return
	}
	if r.Method != "POST" || r.URL.Path != "/command" {
		http.Error(w, "not found", 404)
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 16384)
	if e := r.ParseForm(); e != nil {
		http.Error(w, "bad form", 400)
		return
	}
	if e := s.command(r.PostForm); e != nil {
		s.mu.Lock()
		s.message = clean(e.Error(), 100)
		s.mu.Unlock()
		s.publish()
		http.Error(w, e.Error(), 400)
		return
	}
	s.publish()
	fmt.Fprintln(w, "OK")
}
func main() {
	root := flag.String("root", "/var/lib/paperos/services", "persistent state")
	run := flag.String("run-dir", "/run/paperos", "runtime snapshot and socket")
	apps := flag.String("apps", "/var/lib/paperos/apps", "installed applications")
	packages := flag.String("packages", "/mnt/us/paperos/packages", "received packages")
	simulate := flag.Bool("simulate", false, "never modify host time or network")
	simulatedIP := flag.String("simulate-ip", "", "test-only private address; requires --simulate")
	simulatedTailnetIP := flag.String("simulate-tailnet-ip", "", "test-only Tailscale address; requires --simulate")
	fetch := flag.String("fetch-weather", "", "fetch a real weather cache JSON and exit")
	probeTime := flag.Bool("probe-time", false, "query public network time without changing any clock")
	fetchSpotlight := flag.String("fetch-spotlight", "", "download up to seven real Windows Spotlight images to a cache directory and exit")
	flag.Parse()
	if arguments := flag.Args(); len(arguments) > 0 {
		if arguments[0] == "import-mihome" && len(arguments) == 1 {
			if e := importMiHomeCLI(*run); e != nil {
				log.Fatal(e)
			}
			return
		}
		if arguments[0] == "power-suspend" {
			if e := runSuspendChild(arguments[1:]); e != nil {
				fmt.Fprintln(os.Stderr, e)
				os.Exit(1)
			}
			return
		}
		if arguments[0] != "ctl" || len(arguments) < 2 || (len(arguments)-2)%2 != 0 {
			log.Fatal("usage: paperos-services [--run-dir DIR] ctl COMMAND [KEY VALUE ...]")
		}
		values := url.Values{"cmd": {arguments[1]}}
		for i := 2; i < len(arguments); i += 2 {
			values.Set(arguments[i], arguments[i+1])
		}
		transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(*run, "services.sock"))
		}}
		client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
		response, e := client.PostForm("http://paperos/command", values)
		if e != nil {
			log.Fatal(e)
		}
		data, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		response.Body.Close()
		if response.StatusCode != 200 {
			log.Fatal(string(data))
		}
		fmt.Print(string(data))
		return
	}
	s := &Service{root: *root, run: *run, apps: *apps, packages: *packages, simulate: *simulate || os.Getenv("PAPEROS_EMULATOR") == "1",
		httpClient: &http.Client{Timeout: 15 * time.Second}, weatherURL: "https://api.open-meteo.com/v1/forecast", geocodingURL: "https://geocoding-api.open-meteo.com/v1/search", transfers: map[string]*Transfer{}}
	s.cfg.Clock.Automatic = true
	s.cfg.Lock.IdleSeconds = 300
	if *fetchSpotlight != "" {
		s.root = *fetchSpotlight
		s.run = ""
		s.loadLock()
		s.refreshSpotlight()
		if len(s.spotlight.Entries) == 0 {
			log.Fatal(s.spotlightMessage)
		}
		fmt.Printf("Windows Spotlight: %d/7 cached images\n", len(s.spotlight.Entries))
		return
	}
	if *probeTime {
		sample, e := networkTime(context.Background())
		if e != nil {
			log.Fatal(e)
		}
		data, _ := json.Marshal(sample)
		fmt.Println(string(data))
		return
	}
	if *fetch != "" {
		weather, e := s.fetchWeather()
		if e != nil {
			log.Fatal(e)
		}
		data, _ := json.Marshal(weather)
		if e = atomicWrite(*fetch, data, 0644); e != nil {
			log.Fatal(e)
		}
		return
	}
	if err := os.MkdirAll(s.root, 0700); err != nil {
		log.Fatal(err)
	}
	if err := os.MkdirAll(s.run, 0755); err != nil {
		log.Fatal(err)
	}
	if data, e := os.ReadFile(filepath.Join(s.root, "state.json")); e == nil {
		if e = json.Unmarshal(data, &s.cfg); e != nil {
			log.Fatal("Invalid saved service state: ", e)
		}
	} else if !os.IsNotExist(e) {
		log.Fatal(e)
	}
	if data, e := os.ReadFile(filepath.Join(s.root, "weather-seed.json")); e == nil && s.cfg.Weather.Fetched == 0 {
		_ = json.Unmarshal(data, &s.cfg.Weather)
	}
	s.loadWeatherLocation()
	s.loadLock()
	s.loadSleep()
	s.loadBattery()
	s.loadMiHome()
	s.loadTailnet()
	s.loadStore()
	if *simulatedTailnetIP != "" {
		if !*simulate || !isTailnetIPv4(*simulatedTailnetIP) {
			log.Fatal("simulated Tailscale requires --simulate and a Tailscale IPv4 address")
		}
		s.cfg.Tailnet = TailnetConfig{Version: 1, Enabled: true, AllowReceive: true}
		s.tailnet = TailnetState{Installed: true, Connected: true, Name: "paperos-test", IP: *simulatedTailnetIP, Version: "test", Message: "已连接私有网络（模拟）"}
	}
	if *simulatedIP != "" {
		ip := net.ParseIP(*simulatedIP)
		if !*simulate || ip == nil || ip.To4() == nil || (!ip.IsPrivate() && !ip.IsLoopback() && !ip.IsLinkLocalUnicast()) {
			log.Fatal("simulation requires --simulate and a local IPv4 address")
		}
		s.cfg.WiFi = true
		s.cfg.Airplane = false
		s.net.Connected = true
		s.net.IP = ip.String()
		s.net.SSID = "模拟器测试网络"
	}
	socket := filepath.Join(s.run, "services.sock")
	if old, e := net.DialTimeout("unix", socket, 200*time.Millisecond); e == nil {
		old.Close()
		log.Fatal("services already running")
	}
	_ = os.Remove(socket)
	listener, e := net.Listen("unix", socket)
	if e != nil {
		log.Fatal(e)
	}
	defer os.Remove(socket)
	if e = os.Chmod(socket, 0600); e != nil {
		log.Fatal(e)
	}
	server := &http.Server{Handler: http.HandlerFunc(s.handler), ReadHeaderTimeout: 3 * time.Second, ReadTimeout: 5 * time.Second, WriteTimeout: 5 * time.Second}
	go func() {
		if e := server.Serve(listener); e != nil && !errors.Is(e, http.ErrServerClosed) {
			log.Printf("local server: %v", e)
		}
	}()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
	powerContext, stopPower := context.WithCancel(context.Background())
	defer stopPower()
	if !s.simulate {
		go s.watchPower(powerContext)
	}
	go s.applyNetwork()
	s.mu.Lock()
	if !s.simulate && s.tailnet.Installed {
		s.tailnet.Busy = true
		go s.applyTailnet()
	}
	s.mu.Unlock()
	s.refreshExternalPower()
	s.pollBattery(time.Now(), uptime(), true)
	s.publish()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for n := 0; ; n++ {
		select {
		case <-signals:
			s.pollBattery(time.Now(), uptime(), true)
			s.mu.Lock()
			s.cancelSleepLocked()
			if s.mihome.Cancel != nil {
				s.mihome.Cancel()
			}
			if s.store != nil && s.store.Cancel != nil {
				s.store.Cancel()
			}
			s.mu.Unlock()
			_ = server.Shutdown(context.Background())
			s.mu.Lock()
			receiver := s.receiver
			tailnetReceiver := s.receiverTailnet
			s.mu.Unlock()
			if receiver != nil {
				_ = receiver.Close()
			}
			if tailnetReceiver != nil {
				_ = tailnetReceiver.Close()
			}
			return
		case now := <-ticker.C:
			s.tick(now, uptime(), bootID())
			s.refreshExternalPower()
			s.tickLock(now, uptime())
			s.pollSleep(now, uptime())
			if n%5 == 0 {
				s.pollBattery(now, uptime(), false)
				s.pollNetwork()
				go s.reconcileReceiver()
				s.pollClock()
				s.pollMiHome(false)
				s.pollTailnet(false)
				s.pollStore(now)
			}
			if n%60 == 0 {
				go s.refreshWeather()
				s.pollSpotlight(now)
			}
			s.publish()
		}
	}
}

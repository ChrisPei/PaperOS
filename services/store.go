package main

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	_ "embed"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

//go:embed store-defaults.json
var defaultStoreSources []byte

type StoreSource struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	URL       string `json:"url"`
	BaseURL   string `json:"base_url,omitempty"`
	Format    string `json:"format,omitempty"`
	PublicKey string `json:"public_key,omitempty"`
	Enabled   bool   `json:"enabled"`
	Error     string `json:"error,omitempty"`
}
type StoreEntry struct {
	Key         string   `json:"key"`
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Version     string   `json:"version"`
	Description string   `json:"description"`
	Kind        string   `json:"kind"`
	URL         string   `json:"url"`
	SHA256      string   `json:"sha256,omitempty"`
	Size        int64    `json:"size,omitempty"`
	SourceID    string   `json:"source_id"`
	SourceName  string   `json:"source_name"`
	Reason      string   `json:"reason,omitempty"`
	Platforms   []string `json:"platforms,omitempty"`
	VersionsURL string   `json:"versions_url,omitempty"`
	Homepage    string   `json:"homepage,omitempty"`
	Installed   string   `json:"-"`
	Update      bool     `json:"-"`
}
type StoreReceipt struct {
	ID        string `json:"id"`
	Key       string `json:"key"`
	Name      string `json:"name"`
	Version   string `json:"version"`
	Kind      string `json:"kind"`
	Directory string `json:"directory,omitempty"`
	Digest    string `json:"sha256"`
	Source    string `json:"source"`
}
type StoreJob struct {
	ID        string     `json:"id"`
	Entry     StoreEntry `json:"entry"`
	Phase     string     `json:"phase"`
	Digest    string     `json:"digest"`
	Verified  bool       `json:"verified"`
	Directory string     `json:"directory"`
	Payload   string     `json:"payload"`
	Kind      string     `json:"kind"`
	Percent   int        `json:"percent"`
	Message   string     `json:"message"`
	Bytes     int64      `json:"bytes"`
	Total     int64      `json:"total"`
}
type StoreState struct {
	Sources     []StoreSource           `json:"sources"`
	Entries     []StoreEntry            `json:"entries"`
	Receipts    map[string]StoreReceipt `json:"receipts"`
	Refreshed   int64                   `json:"refreshed"`
	Job         *StoreJob               `json:"job,omitempty"`
	Revision    uint64                  `json:"-"`
	Published   uint64                  `json:"-"`
	Busy        bool                    `json:"-"`
	Message     string                  `json:"-"`
	Cancel      context.CancelFunc      `json:"-"`
	LastAttempt time.Time               `json:"-"`
	Cancelled   bool                    `json:"-"`
}

func (s *Service) storePath(name string) string { return filepath.Join(s.root, "store", name) }
func (s *Service) saveStoreLocked() error {
	b, e := json.MarshalIndent(s.store, "", "  ")
	if e != nil {
		return e
	}
	return atomicWrite(s.storePath("state.json"), b, 0600)
}
func (s *Service) storeChangedLocked() {
	s.store.Revision++
	if s.store.Revision == 0 {
		s.store.Revision = 1
	}
}
func (s *Service) loadStore() {
	s.store = &StoreState{Receipts: map[string]StoreReceipt{}, Revision: 1}
	loaded := false
	if data, e := os.ReadFile(s.storePath("state.json")); e == nil {
		if json.Unmarshal(data, s.store) != nil {
			s.store.Message = "应用商店缓存损坏，请刷新目录"
		} else {
			loaded = true
		}
	}
	if !loaded {
		_ = json.Unmarshal(defaultStoreSources, &s.store.Sources)
	}
	for i := range s.store.Sources {
		source := &s.store.Sources[i]
		if source.ID == "paperos" && source.URL == "https://raw.githubusercontent.com/ChrisPei/paperos-apps/main/catalog.json" && source.PublicKey == "CgXy+esu043BN6ZwFFU7U0bBPAP4JyrUsx07tiuBLMY=" {
			source.URL = "https://api.github.com/repos/ChrisPei/paperos-apps/contents/catalog.json"
		}
	}
	if s.store.Receipts == nil {
		s.store.Receipts = map[string]StoreReceipt{}
	}
	if job := s.store.Job; job != nil && job.Phase != "done" && job.Phase != "error" {
		// Do not restore an in-flight install, or execute anything during service boot.
		job.Phase = "error"
		job.Message = "上次操作已中断，请重新下载；已安装版本保留"
		s.store.Message = job.Message
	}
	// Fit the native ARM unsigned long and avoid a stale UI after service restart.
	s.store.Revision = uint64(time.Now().UnixNano()&0x7fffffff) + 1
	s.store.Published = 0
	s.store.Busy = false
	s.recoverStorePlugins()
	s.syncStoreInstalledLocked()
}
func storeVersionCompare(a, b string) int {
	a = strings.TrimPrefix(a, "v")
	b = strings.TrimPrefix(b, "v")
	if a == b {
		return 0
	}
	if strings.HasPrefix(a, "git:") || strings.HasPrefix(b, "git:") {
		return 1
	}
	parse := func(v string) ([]int, string) {
		v, _, _ = strings.Cut(v, "+")
		main, pre, _ := strings.Cut(v, "-")
		var n []int
		for _, x := range strings.Split(main, ".") {
			i, e := strconv.Atoi(x)
			if e != nil {
				return nil, v
			}
			n = append(n, i)
		}
		return n, pre
	}
	x, xpre := parse(a)
	y, ypre := parse(b)
	if x == nil || y == nil {
		if a > b {
			return 1
		}
		return -1
	}
	for i := 0; i < len(x) || i < len(y); i++ {
		u, v := 0, 0
		if i < len(x) {
			u = x[i]
		}
		if i < len(y) {
			v = y[i]
		}
		if u > v {
			return 1
		}
		if u < v {
			return -1
		}
	}
	if xpre == ypre {
		return 0
	}
	if xpre == "" {
		return 1
	}
	if ypre == "" {
		return -1
	}
	if xpre > ypre {
		return 1
	}
	return -1
}
func storeSlug(text string) string {
	text = strings.ToLower(text)
	var b strings.Builder
	for _, r := range text {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-' || r == '_' || r == '.' {
			b.WriteRune(r)
		} else {
			b.WriteByte('-')
		}
	}
	result := strings.Trim(b.String(), ".-_")
	if len(result) > 48 {
		result = result[:48]
	}
	return result
}
func (s *Service) syncStoreInstalledLocked() {
	if s.store == nil {
		return
	}
	versions := map[string]string{}
	if rows, e := os.ReadDir(s.apps); e == nil {
		for _, d := range rows {
			if strings.HasPrefix(d.Name(), ".") || !d.IsDir() {
				continue
			}
			if m, e := readAppManifest(filepath.Join(s.apps, d.Name())); e == nil {
				versions[m["id"]] = m["version"]
			}
		}
	}
	changed := false
	for _, receipt := range s.store.Receipts {
		if receipt.Kind != "koplugin" || receipt.Directory != s.storePluginDirectory(receipt.ID) {
			continue
		}
		if st, e := os.Stat(filepath.Join(receipt.Directory, "main.lua")); e != nil || !st.Mode().IsRegular() {
			continue
		}
		found := false
		for _, entry := range s.store.Entries {
			if entry.ID == receipt.ID && entry.Key == receipt.Key {
				found = true
				break
			}
		}
		if !found && len(s.store.Entries) < storeMaxEntries-1 {
			s.store.Entries = append(s.store.Entries, StoreEntry{Key: receipt.Key, ID: receipt.ID, Name: receipt.Name, Version: receipt.Version, Kind: "koplugin", Installed: receipt.Version, SourceID: "installed", SourceName: receipt.Source})
			changed = true
		}
	}
	for i := range s.store.Entries {
		entry := &s.store.Entries[i]
		version := versions[entry.ID]
		origin := true
		if receipt, ok := s.store.Receipts[entry.ID]; ok && receipt.Kind == "koplugin" {
			origin = receipt.Key == entry.Key
			version = ""
			expected := s.storePluginDirectory(receipt.ID)
			if expected == receipt.Directory {
				if info, e := os.Stat(filepath.Join(expected, "main.lua")); e == nil && info.Mode().IsRegular() {
					if origin {
						version = receipt.Version
					}
				}
			}
		}
		update := origin && version != "" && !storeUnresolvedVersion(entry.Version) && storeVersionCompare(entry.Version, version) > 0 && entry.Reason == ""
		if entry.Installed != version || entry.Update != update {
			entry.Installed = version
			entry.Update = update
			changed = true
		}
	}
	if changed {
		s.storeChangedLocked()
	}
}
func storeURL(value string, simulate bool) (*url.URL, error) {
	u, e := url.Parse(strings.TrimSpace(value))
	if e != nil || u.Hostname() == "" || u.User != nil || u.Fragment != "" {
		return nil, errors.New("请输入不含账号密码的 HTTPS 地址")
	}
	if u.Scheme != "https" {
		ip := net.ParseIP(u.Hostname())
		if !simulate || u.Scheme != "http" || ip == nil || !ip.IsLoopback() {
			return nil, errors.New("应用源和下载地址必须使用 HTTPS")
		}
	}
	return u, nil
}
func (s *Service) storeHTTPClient() *http.Client {
	s.storeClientOnce.Do(func() {
		if s.storeClient != nil {
			return
		}
		s.storeClient = &http.Client{Timeout: 20 * time.Minute, Transport: &http.Transport{Proxy: http.ProxyFromEnvironment, ForceAttemptHTTP2: true, DialContext: (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext, TLSHandshakeTimeout: 12 * time.Second, ResponseHeaderTimeout: 20 * time.Second, IdleConnTimeout: 60 * time.Second}, CheckRedirect: func(r *http.Request, via []*http.Request) error {
			if len(via) > 8 {
				return errors.New("下载重定向过多")
			}
			_, e := storeURL(r.URL.String(), s.simulate)
			return e
		}}
	})
	return s.storeClient
}
func (s *Service) storeFetch(ctx context.Context, address string, limit int64) ([]byte, error) {
	var last error
	for _, candidate := range storeMetadataAddresses(address) {
		attempt, cancel := context.WithTimeout(ctx, 25*time.Second)
		data, err := s.storeFetchOnce(attempt, candidate, limit)
		cancel()
		if err == nil {
			return data, nil
		}
		last = err
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
	}
	return nil, last
}
func (s *Service) storeFetchOnce(ctx context.Context, address string, limit int64) ([]byte, error) {
	if _, e := storeURL(address, s.simulate); e != nil {
		return nil, e
	}
	request, e := http.NewRequestWithContext(ctx, "GET", address, nil)
	if e != nil {
		return nil, e
	}
	request.Header.Set("User-Agent", "PaperOS-App-Store/1.0")
	request.Header.Set("Accept", "application/json")
	storeDownloadHeaders(request)
	response, e := s.storeHTTPClient().Do(request)
	if e != nil {
		return nil, e
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return nil, fmt.Errorf("软件源返回 HTTP %d", response.StatusCode)
	}
	b, e := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if e != nil {
		return nil, e
	}
	if int64(len(b)) > limit {
		return nil, errors.New("软件源响应过大")
	}
	return b, nil
}
func (s *Service) storeFetchSource(ctx context.Context, source StoreSource) ([]StoreEntry, error) {
	data, e := s.storeFetch(ctx, source.URL, 2<<20)
	if e != nil {
		return nil, e
	}
	if source.PublicKey != "" {
		key, e := base64.StdEncoding.DecodeString(source.PublicKey)
		if e != nil || len(key) != ed25519.PublicKeySize {
			return nil, errors.New("应用源公钥无效")
		}
		sig, e := s.storeFetch(ctx, source.URL+".sig", 4096)
		if e != nil {
			return nil, e
		}
		raw := sig
		if len(raw) != ed25519.SignatureSize {
			raw, e = base64.StdEncoding.DecodeString(strings.TrimSpace(string(sig)))
		}
		if e != nil || !ed25519.Verify(key, data, raw) {
			return nil, errors.New("应用目录签名验证失败，保留旧目录")
		}
	}
	if source.Format == "koreader-contrib" {
		return s.fetchStoreContrib(ctx, source, data)
	}
	return parseStoreCatalog(data, source)
}
func (s *Service) refreshStore() {
	s.mu.Lock()
	sources := append([]StoreSource(nil), s.store.Sources...)
	previous := append([]StoreEntry(nil), s.store.Entries...)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	if s.store.Cancelled {
		cancel()
	}
	s.store.Cancel = cancel
	s.mu.Unlock()
	defer cancel()
	var entries []StoreEntry
	var failures []string
	for i := range sources {
		source := &sources[i]
		if !source.Enabled {
			continue
		}
		items, e := s.storeFetchSource(ctx, *source)
		if e == nil {
			for j := range items {
				if !storeUnresolvedVersion(items[j].Version) || items[j].Reason != "" {
					continue
				}
				for _, old := range previous {
					if old.Key == items[j].Key && old.Installed != "" {
						if resolved, err := s.resolveStoreEntry(ctx, items[j]); err == nil {
							items[j] = resolved
						}
						break
					}
				}
			}
		}
		if e == nil && len(entries)+len(items) > storeMaxEntries-64 {
			e = errors.New("目录总量超过 960 项，请停用部分应用源后重试")
			items = nil
		}
		if e != nil {
			source.Error = clean(e.Error(), 120)
			failures = append(failures, source.Name+": "+source.Error)
			for _, old := range previous {
				if old.SourceID == source.ID && len(entries)+len(items) < storeMaxEntries-64 {
					items = append(items, old)
				}
			}
		} else {
			source.Error = ""
		}
		entries = append(entries, items...)
	}
	order := map[string]int{}
	for i, source := range sources {
		order[source.ID] = i
	}
	sort.SliceStable(entries, func(i, j int) bool {
		if entries[i].SourceID != entries[j].SourceID {
			return order[entries[i].SourceID] < order[entries[j].SourceID]
		}
		return entries[i].Name < entries[j].Name
	})
	s.mu.Lock()
	defer s.mu.Unlock()
	s.store.Sources = sources
	s.store.Entries = entries
	s.store.Busy = false
	s.store.Cancel = nil
	if len(failures) > 0 {
		s.store.Message = strings.Join(failures, "；")
	} else {
		s.store.Refreshed = time.Now().Unix()
		s.store.Message = fmt.Sprintf("目录已更新 · %d 款应用", len(entries))
	}
	s.syncStoreInstalledLocked()
	s.storeChangedLocked()
	_ = s.saveStoreLocked()
}
func (s *Service) pollStore(now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.store == nil {
		return
	}
	s.syncStoreInstalledLocked()
	if !s.simulate && s.net.Connected && !s.cfg.Airplane && !s.store.Busy && !s.sleep.Busy && now.Sub(s.store.LastAttempt) > 10*time.Minute && now.Unix()-s.store.Refreshed > 6*3600 {
		s.store.Busy = true
		s.store.Cancelled = false
		s.store.LastAttempt = now
		s.store.Message = "正在检查应用更新"
		s.storeChangedLocked()
		go s.refreshStore()
	}
}
func (s *Service) storeFindLocked(key string) (StoreEntry, bool) {
	for _, e := range s.store.Entries {
		if e.Key == key {
			return e, true
		}
	}
	if s.store.Job != nil && s.store.Job.Entry.Key == key {
		return s.store.Job.Entry, true
	}
	return StoreEntry{}, false
}
func (s *Service) storeCommandLocked(v url.Values) (bool, error) {
	name := v.Get("cmd")
	if !strings.HasPrefix(name, "store-") {
		return false, nil
	}
	if s.store == nil {
		return true, errors.New("应用商店尚未初始化")
	}
	fail := func(msg string) (bool, error) { return true, errors.New(msg) }
	switch name {
	case "store-sync":
		s.syncStoreInstalledLocked()
		return true, nil
	case "store-refresh":
		if s.store.Busy {
			return fail("正在处理上一项操作")
		}
		s.store.Busy = true
		s.store.Cancelled = false
		s.store.Message = "正在刷新应用目录"
		s.store.LastAttempt = time.Now()
		s.storeChangedLocked()
		go s.refreshStore()
	case "store-source-add":
		if s.store.Busy {
			return fail("请等当前操作完成")
		}
		var source StoreSource
		var e error
		if id := v.Get("preset"); id != "" {
			var okay bool
			source, okay = storePreset(id)
			if !okay {
				return fail("未知的社区应用源")
			}
			source.Enabled = true
		} else {
			source, e = storeSourceAddress(strings.TrimSpace(v.Get("url")), s.simulate)
			if e != nil {
				return true, e
			}
		}
		if len(s.store.Sources) >= 8 {
			return fail("最多添加 8 个应用源")
		}
		for _, src := range s.store.Sources {
			if src.URL == source.URL || (source.ID != "" && src.ID == source.ID) {
				return fail("这个应用源已经存在")
			}
		}
		if source.ID == "" {
			sum := sha256.Sum256([]byte(source.URL))
			source.ID = "source-" + hex.EncodeToString(sum[:6])
		}
		if name := clean(v.Get("name"), 40); name != "" {
			source.Name = name
		}
		s.store.Sources = append(s.store.Sources, source)
		s.store.Message = "应用源已添加，点刷新获取目录"
		s.storeChangedLocked()
		return true, s.saveStoreLocked()
	case "store-source-toggle", "store-source-remove":
		if s.store.Busy {
			return fail("请等当前操作完成")
		}
		found := false
		for i := range s.store.Sources {
			if s.store.Sources[i].ID == v.Get("id") {
				if name == "store-source-remove" {
					s.store.Sources = append(s.store.Sources[:i], s.store.Sources[i+1:]...)
					kept := s.store.Entries[:0]
					for _, entry := range s.store.Entries {
						if entry.SourceID != v.Get("id") {
							kept = append(kept, entry)
						}
					}
					s.store.Entries = kept
					if job := s.store.Job; job != nil && job.Entry.SourceID == v.Get("id") {
						if job.Directory == s.storeJobDirectory(job.ID) {
							go os.RemoveAll(job.Directory)
						}
						s.store.Job = nil
					}
					s.syncStoreInstalledLocked()
				} else {
					s.store.Sources[i].Enabled = !s.store.Sources[i].Enabled
				}
				found = true
				break
			}
		}
		if !found {
			return fail("应用源不存在")
		}
		s.storeChangedLocked()
		return true, s.saveStoreLocked()
	case "store-download", "store-import":
		if s.store.Busy {
			return fail("请等当前下载或安装完成")
		}
		var entry StoreEntry
		if name == "store-import" {
			address := strings.TrimSpace(v.Get("url"))
			if _, e := storeURL(address, s.simulate); e != nil {
				return true, e
			}
			sum := sha256.Sum256([]byte(address))
			entry = StoreEntry{Key: "direct-" + hex.EncodeToString(sum[:8]), ID: "org.paperos.import", Name: "下载链接", Version: "待识别", Kind: "auto", URL: address, SourceID: "direct", SourceName: "直接下载"}
		}
		if name == "store-download" {
			var ok bool
			entry, ok = s.storeFindLocked(v.Get("key"))
			if !ok {
				return fail("应用目录已变化，请重新选择")
			}
			if entry.Reason != "" {
				return fail(entry.Reason)
			}
			if entry.SourceID != "direct" {
				enabled := false
				for _, src := range s.store.Sources {
					if src.ID == entry.SourceID && src.Enabled {
						enabled = true
					}
				}
				if !enabled {
					return fail("这个应用源已停用")
				}
			}
		}
		if entry.URL == "" && entry.VersionsURL == "" {
			return fail("此条目没有可用下载地址")
		}
		if old := s.store.Job; old != nil && s.storeJobDirectory(old.ID) == old.Directory {
			go os.RemoveAll(old.Directory)
		}
		job := &StoreJob{ID: randomID(), Entry: entry, Phase: "downloading", Message: "正在连接下载源"}
		job.Directory = s.storeJobDirectory(job.ID)
		s.store.Job = job
		s.store.Busy = true
		s.store.Cancelled = false
		s.store.Message = job.Message
		s.storeChangedLocked()
		_ = s.saveStoreLocked()
		go s.downloadStore(job.ID)
	case "store-cancel":
		if s.store.Job != nil && s.store.Job.Phase == "installing" {
			return fail("正在安装，请稍候")
		}
		if s.store.Cancel != nil {
			s.store.Cancel()
		}
		s.store.Cancelled = true
		return true, nil
	case "store-install":
		job := s.store.Job
		if job == nil || job.ID != v.Get("id") || job.Digest != v.Get("digest") || job.Phase != "ready" {
			return fail("待安装文件已变化，请重新下载确认")
		}
		if s.store.Busy {
			return fail("应用库忙碌，请稍后重试")
		}
		job.Phase = "installing"
		job.Message = "正在安装；已有数据会保留"
		s.store.Busy = true
		s.storeChangedLocked()
		_ = s.saveStoreLocked()
		go s.installStore(job.ID)
	case "store-remove":
		if s.store.Busy {
			return fail("应用库忙碌，请稍后重试")
		}
		entry, ok := s.storeFindLocked(v.Get("key"))
		if !ok {
			return fail("应用不存在")
		}
		receipt, ok := s.store.Receipts[entry.ID]
		if !ok || receipt.Kind != "koplugin" {
			return fail("请在已安装应用页卸载这个程序")
		}
		s.store.Busy = true
		s.store.Message = "正在卸载插件，个人数据保留"
		s.storeChangedLocked()
		go s.removeStorePlugin(receipt)
	default:
		return fail("未知应用商店命令")
	}
	return true, nil
}
func (s *Service) storeJobDirectory(id string) string { return filepath.Join(s.packages, ".store-"+id) }
func (s *Service) storeJobUpdate(id, phase, message string, percent int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if j := s.store.Job; j != nil && j.ID == id {
		j.Phase = phase
		j.Message = clean(message, 160)
		j.Percent = percent
		s.store.Message = j.Message
		s.storeChangedLocked()
	}
}
func (s *Service) downloadStore(id string) {
	s.mu.Lock()
	if s.store.Job == nil || s.store.Job.ID != id {
		s.mu.Unlock()
		return
	}
	job := *s.store.Job
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	if s.store.Cancelled {
		cancel()
	}
	s.store.Cancel = cancel
	s.mu.Unlock()
	defer cancel()
	err := func() error {
		var e error
		job.Entry, e = s.resolveStoreEntry(ctx, job.Entry)
		if e != nil {
			return e
		}
		job.Entry.URL, e = s.storeAssetURL(ctx, job.Entry.URL, job.Entry.SHA256)
		if e != nil {
			return e
		}
		if _, e = storeURL(job.Entry.URL, s.simulate); e != nil {
			return e
		}
		if e = os.MkdirAll(job.Directory, 0700); e != nil {
			return e
		}
		if e = storeFreeSpace(job.Directory, 8<<20); e != nil {
			return e
		}
		request, e := http.NewRequestWithContext(ctx, "GET", job.Entry.URL, nil)
		if e != nil {
			return e
		}
		request.Header.Set("User-Agent", "PaperOS-App-Store/1.0")
		storeDownloadHeaders(request)
		response, e := s.storeHTTPClient().Do(request)
		if e != nil {
			return e
		}
		defer response.Body.Close()
		if response.StatusCode != 200 {
			return fmt.Errorf("下载返回 HTTP %d", response.StatusCode)
		}
		if response.ContentLength > storeMaxArchive {
			return errors.New("安装包超过 64 MiB")
		}
		out, e := os.OpenFile(filepath.Join(job.Directory, "download"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			return e
		}
		hash := sha256.New()
		buffer := make([]byte, 64<<10)
		var done int64
		last := -1
		for {
			n, readErr := response.Body.Read(buffer)
			if n > 0 {
				done += int64(n)
				if done > storeMaxArchive {
					out.Close()
					return errors.New("下载文件超过 64 MiB")
				}
				if _, e = out.Write(buffer[:n]); e != nil {
					out.Close()
					return e
				}
				hash.Write(buffer[:n])
				percent := 0
				if response.ContentLength > 0 {
					percent = int(done * 100 / response.ContentLength)
				}
				if percent != last {
					last = percent
					s.storeJobUpdate(id, "downloading", fmt.Sprintf("正在下载 · %.1f MiB", float64(done)/(1<<20)), percent)
				}
			}
			if readErr == io.EOF {
				break
			}
			if readErr != nil {
				out.Close()
				return readErr
			}
		}
		e = out.Sync()
		closeErr := out.Close()
		if e != nil {
			return e
		}
		if closeErr != nil {
			return closeErr
		}
		job.Digest = hex.EncodeToString(hash.Sum(nil))
		job.Bytes = done
		job.Total = response.ContentLength
		if job.Entry.SHA256 != "" {
			if !strings.EqualFold(strings.TrimPrefix(job.Entry.SHA256, "sha256:"), job.Digest) {
				return errors.New("SHA-256 与应用源不一致，拒绝安装")
			}
			job.Verified = true
		}
		s.storeJobUpdate(id, "preparing", "下载完成，正在检查安装包", 100)
		if e = unpackStoreArchive(filepath.Join(job.Directory, "download"), filepath.Join(job.Directory, "content")); e != nil {
			return e
		}
		job.Payload, job.Kind, e = storeFindPayload(filepath.Join(job.Directory, "content"))
		if e != nil {
			return e
		}
		if job.Entry.Kind != "auto" && job.Entry.Kind != "" && job.Entry.Kind != job.Kind {
			return errors.New("安装包类型与应用源声明不符")
		}
		if job.Kind == "papp" {
			m, e := storeValidateNative(job.Payload)
			if e != nil {
				return e
			}
			if job.Entry.SourceID != "direct" && (m["id"] != job.Entry.ID || m["version"] != job.Entry.Version) {
				return errors.New("应用编号或版本与目录不一致")
			}
			job.Entry.ID = m["id"]
			job.Entry.Name = m["name"]
			job.Entry.Version = m["version"]
		} else {
			if _, e := readAppManifest(filepath.Join(s.apps, "org.paperos.koreader")); e != nil {
				return errors.New("此安装包是 KOReader 插件，请先安装 KOReader")
			}
			if job.Entry.SourceID == "direct" {
				base := strings.TrimSuffix(filepath.Base(job.Payload), ".koplugin")
				if !strings.HasSuffix(filepath.Base(job.Payload), ".koplugin") {
					base = "plugin-" + job.Digest[:12]
				}
				// Read a literal metadata name without evaluating downloaded Lua.
				if meta, err := os.ReadFile(filepath.Join(job.Payload, "_meta.lua")); err == nil && len(meta) < 64<<10 {
					if match := regexp.MustCompile(`\bname\s*=\s*["']([a-zA-Z0-9_.-]{1,48})["']`).FindSubmatch(meta); len(match) == 2 {
						base = string(match[1])
					}
				}
				job.Entry.ID = "koplugin." + storeSlug(base)
				job.Entry.Name = base
				job.Entry.Version = "sha-" + job.Digest[:10]
			}
		}
		job.Entry.Kind = job.Kind
		if e = ctx.Err(); e != nil {
			return errors.New("下载已取消")
		}
		job.Phase = "ready"
		job.Message = "下载完成，请确认安装"
		job.Percent = 100
		return nil
	}()
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.store.Job == nil || s.store.Job.ID != id {
		return
	}
	s.store.Busy = false
	s.store.Cancel = nil
	if s.store.Cancelled {
		err = errors.New("下载已取消")
	}
	if err != nil {
		s.store.Job.Phase = "error"
		s.store.Job.Message = clean(err.Error(), 180)
		s.store.Message = s.store.Job.Message
		go os.RemoveAll(job.Directory)
	} else {
		s.store.Job = &job
		for i := range s.store.Entries {
			if s.store.Entries[i].Key == job.Entry.Key {
				s.store.Entries[i] = job.Entry
			}
		}
		s.store.Message = job.Message
	}
	s.storeChangedLocked()
	_ = s.saveStoreLocked()
}
func storeFileDigest(name string) (string, error) {
	f, e := os.Open(name)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	_, e = io.Copy(h, io.LimitReader(f, storeMaxArchive+1))
	return hex.EncodeToString(h.Sum(nil)), e
}
func (s *Service) installStore(id string) {
	s.mu.Lock()
	job := *s.store.Job
	s.mu.Unlock()
	err := func() error {
		if job.ID != id || job.Directory != s.storeJobDirectory(id) || !strings.HasPrefix(job.Payload, job.Directory+string(filepath.Separator)) {
			return errors.New("安装路径无效")
		}
		digest, e := storeFileDigest(filepath.Join(job.Directory, "download"))
		if e != nil || digest != job.Digest {
			return errors.New("下载文件已变化，请重新下载")
		}
		// Re-extract the verified bytes into a new tree, so no mutable staged file
		// can replace the payload between review and confirmation.
		reviewed := filepath.Join(job.Directory, "confirmed")
		if e = unpackStoreArchive(filepath.Join(job.Directory, "download"), reviewed); e != nil {
			return e
		}
		payload, kind, e := storeFindPayload(reviewed)
		if e != nil {
			return e
		}
		if kind != job.Kind {
			return errors.New("安装类型已变化")
		}
		if kind == "papp" {
			m, e := storeValidateNative(payload)
			if e != nil {
				return e
			}
			if m["id"] != job.Entry.ID || m["version"] != job.Entry.Version {
				return errors.New("应用身份已变化")
			}
			var size int64
			_ = filepath.WalkDir(payload, func(p string, d os.DirEntry, e error) error {
				if e != nil {
					return e
				}
				if !d.IsDir() {
					if st, e := d.Info(); e == nil {
						size += st.Size()
					}
				}
				return nil
			})
			if e = storeFreeSpace(s.apps, size+(8<<20)); e != nil {
				return e
			}
			binary := s.storeInstaller
			if binary == "" {
				binary = "/usr/bin/paperos"
			}
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
			defer cancel()
			cmd := exec.CommandContext(ctx, binary, "--app-root", s.apps, "--install", payload)
			output, e := cmd.CombinedOutput()
			if e != nil {
				return fmt.Errorf("安装未完成，原版本保留: %s", clean(string(output), 140))
			}
			return nil
		}
		confirmedEntry := job.Entry
		confirmedEntry.SHA256 = job.Digest
		return s.installStorePlugin(confirmedEntry, payload)
	}()
	s.mu.Lock()
	defer s.mu.Unlock()
	s.store.Busy = false
	if err != nil {
		s.store.Job.Phase = "error"
		s.store.Job.Message = clean(err.Error(), 180)
		s.store.Message = s.store.Job.Message
	} else {
		receipt := StoreReceipt{ID: job.Entry.ID, Key: job.Entry.Key, Name: job.Entry.Name, Version: job.Entry.Version, Kind: job.Kind, Digest: job.Digest, Source: job.Entry.SourceName}
		if job.Kind == "koplugin" {
			receipt.Directory = s.storePluginDirectory(job.Entry.ID)
		}
		s.store.Receipts[job.Entry.ID] = receipt
		s.store.Job.Phase = "done"
		s.store.Job.Message = "安装完成，已有数据已保留"
		s.store.Message = s.store.Job.Message
		found := false
		for i, entry := range s.store.Entries {
			if entry.Key == job.Entry.Key {
				s.store.Entries[i] = job.Entry
				found = true
			}
		}
		if !found {
			s.store.Entries = append(s.store.Entries, job.Entry)
		}
	}
	s.syncStoreInstalledLocked()
	s.storeChangedLocked()
	_ = s.saveStoreLocked()
	go os.RemoveAll(job.Directory)
}
func (s *Service) publishStoreLocked(b *strings.Builder) {
	if s.store == nil {
		return
	}
	store := s.store
	phase, progress, jobID, key, digest := "idle", 0, "", "", ""
	if job := store.Job; job != nil {
		phase = job.Phase
		progress = job.Percent
		jobID = job.ID
		key = job.Entry.Key
		digest = job.Digest
	}
	catalog := filepath.Join(s.run, "store.tsv")
	if store.Published != store.Revision {
		var body strings.Builder
		fmt.Fprintf(&body, "paperos-store-v1\t%d\n", store.Revision)
		for _, source := range store.Sources {
			fmt.Fprintf(&body, "source\t%s\t%s\t%s\t%s\t%t\t%s\n", field(source.ID), field(source.Name), field(source.URL), field(source.Format), source.Enabled, field(source.Error))
		}
		entries := append([]StoreEntry(nil), store.Entries...)
		if job := store.Job; job != nil {
			found := false
			for _, entry := range entries {
				if entry.Key == job.Entry.Key {
					found = true
				}
			}
			if !found {
				if len(entries) >= storeMaxEntries {
					entries = entries[:storeMaxEntries-1]
				}
				entries = append(entries, job.Entry)
			}
		}
		for _, preset := range storePresets() {
			added := false
			for _, source := range store.Sources {
				if source.ID == preset.ID || source.URL == preset.URL {
					added = true
				}
			}
			description := "社区包；安装前检查兼容性"
			if preset.PublicKey != "" {
				description = "Ed25519 签名目录"
			}
			if preset.ID == "koreader-contrib" {
				description = "固定 Git 提交版本的 KOReader 插件"
			}
			if preset.ID == "kpm" {
				description = "可浏览目录；原厂系统包需要移植"
			}
			fmt.Fprintf(&body, "preset\t%s\t%s\t%s\t%s\t%t\t%s\n", field(preset.ID), field(preset.Name), field(preset.URL), field(preset.Format), added, description)
		}
		for _, entry := range entries {
			fmt.Fprintf(&body, "app\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%d\t%s\t%s\t%t\t%s\t%s\n", field(entry.Key), field(entry.ID), field(entry.Name), field(entry.Version), field(entry.Installed), field(entry.Kind), field(entry.SourceName), entry.Size, field(entry.Reason), field(entry.Description), entry.Update, field(entry.URL), field(entry.SHA256))
		}
		if atomicWrite(catalog, []byte(body.String()), 0644) == nil {
			store.Published = store.Revision
		}
	}
	fmt.Fprintf(b, "store\t%t\t%s\t%d\t%d\t%s\t%s\t%s\t%s\t%s\n", store.Busy, phase, progress, store.Revision, field(catalog), field(store.Message), field(jobID), field(key), field(digest))
}

func storeFreeSpace(directory string, needed int64) error {
	var fs syscall.Statfs_t
	if e := syscall.Statfs(directory, &fs); e != nil {
		return e
	}
	if uint64(fs.Bavail)*uint64(fs.Bsize) < uint64(needed) {
		return errors.New("存储空间不足，原版本保留；请清理下载缓存后再试")
	}
	return nil
}

func storeDownloadHeaders(request *http.Request) {
	if request.URL.Hostname() == "api.github.com" {
		if strings.Contains(request.URL.Path, "/contents/") {
			request.Header.Set("Accept", "application/vnd.github.raw+json")
		}
		if strings.Contains(request.URL.Path, "/releases/assets/") {
			request.Header.Set("Accept", "application/octet-stream")
		}
	}
}

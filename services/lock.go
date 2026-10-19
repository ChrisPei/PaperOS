package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/color"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// The lock is shared by native applications and the input method. Sleep planning
// waits for its rendered wallpaper and programs the next reminder into the RTC.
type LockConfig struct {
	IdleSeconds, PoweredMultiplier int
}
type LockState struct {
	Locked       bool
	LastActivity float64
	Generation   uint64
}
type SpotlightImage struct {
	ID, SHA256, URL, Title, Copyright string
	Added                             int64
}
type SpotlightCache struct {
	Version                  int
	Day, Current, UpdatedDay string
	Entries                  []SpotlightImage
	Mode                     string
	Favorites                []SpotlightImage
	Fixed                    *SpotlightImage
	Revision                 uint64
}

const spotlightEndpoint = "https://fd.api.iris.microsoft.com/v4/api/selection"
const spotlightLimit = 7
const lockPGMHeader = "P5\n600 800\n255\n"
const lockThumbHeader = "P5\n150 200\n255\n"

func (s *Service) cacheDir() string           { return filepath.Join(s.root, "lockscreen") }
func (s *Service) photoPath(id string) string { return filepath.Join(s.cacheDir(), id+".pgm") }
func validPhotoID(id string) bool {
	b, e := hex.DecodeString(id)
	return e == nil && len(b) == sha256.Size && id == strings.ToLower(id)
}
func validIdle(n int) bool {
	return n == 0 || n == 60 || n == 180 || n == 300 || n == 600 || n == 900 || n == 1800
}
func (s *Service) saveSpotlightLocked() error {
	version, revision := s.spotlight.Version, s.spotlight.Revision
	s.spotlight.Version = 2
	s.spotlight.Revision++
	b, e := json.MarshalIndent(s.spotlight, "", "  ")
	if e != nil {
		return e
	}
	e = atomicWrite(filepath.Join(s.cacheDir(), "index.json"), append(b, '\n'), 0600)
	if e != nil {
		s.spotlight.Version, s.spotlight.Revision = version, revision
	}
	return e
}
func (s *Service) persistLockLocked() error {
	b, e := json.Marshal(s.lock)
	if e != nil {
		return e
	}
	return atomicWrite(filepath.Join(s.run, "lock.json"), b, 0600)
}
func (s *Service) loadLock() {
	if !validIdle(s.cfg.Lock.IdleSeconds) {
		s.cfg.Lock.IdleSeconds = 300
	}
	if !validPoweredMultiplier(s.cfg.Lock.PoweredMultiplier) {
		s.cfg.Lock.PoweredMultiplier = 5
	}
	s.lock.LastActivity = uptime()
	if s.run != "" {
		if b, e := os.ReadFile(filepath.Join(s.run, "lock.json")); e == nil {
			var state LockState
			if json.Unmarshal(b, &state) == nil {
				s.lock.Locked, s.lock.Generation = state.Locked, state.Generation
			}
		}
	}
	var cached SpotlightCache
	if b, e := os.ReadFile(filepath.Join(s.cacheDir(), "index.json")); e == nil && len(b) < 262144 && json.Unmarshal(b, &cached) == nil && (cached.Version == 1 || cached.Version == 2) {
		s.loadGallery(cached)
	}
	if s.spotlight.Mode == "" {
		s.spotlight.Mode = "daily"
	}
	if s.spotlight.Revision == 0 {
		s.spotlight.Revision = 1
	}
	s.selectPhotoLocked(time.Now())
	if s.spotlight.Version == 1 {
		if e := s.saveSpotlightLocked(); e != nil {
			log.Printf("wallpaper index migration: %v", e)
		}
	}
	if len(s.spotlight.Entries) == 0 {
		s.spotlightMessage = "联网后自动缓存 Windows 聚焦图片"
	} else {
		s.spotlightMessage = fmt.Sprintf("Windows 聚焦 · 已缓存 %d/7 张", len(s.spotlight.Entries))
	}
	s.pruneSpotlightLocked()
}
func (s *Service) pruneSpotlightLocked() {
	keep := map[string]bool{}
	for _, im := range s.galleryImagesLocked() {
		keep[im.ID] = true
	}
	files, _ := os.ReadDir(s.cacheDir())
	for _, file := range files {
		name := file.Name()
		if !file.IsDir() && strings.HasSuffix(name, ".pgm") {
			id := strings.TrimSuffix(strings.TrimSuffix(name, ".pgm"), ".thumb")
			if validPhotoID(id) && !keep[id] {
				_ = os.Remove(filepath.Join(s.cacheDir(), name))
			}
		}
	}
}
func (s *Service) selectPhotoLocked(now time.Time) {
	previous := s.spotlight // Selection only changes scalar fields; avoid allocating on every tick.
	if s.choosePhotoLocked(now, false) {
		if e := s.saveSpotlightLocked(); e != nil {
			s.spotlight = previous
			log.Printf("wallpaper selection: %v", e)
		}
	}
}
func (s *Service) tickLock(now time.Time, boot float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.selectPhotoLocked(now)
	if idle := s.effectiveIdleLocked(); !s.lock.Locked && idle > 0 && boot-s.lock.LastActivity >= float64(idle) {
		s.advanceFavoriteLocked(now)
		s.lock.Locked = true
		s.lock.Generation++
		_ = s.persistLockLocked()
	}
}
func (s *Service) lockCommandLocked(v url.Values, boot float64) (bool, error) {
	switch v.Get("cmd") {
	case "lock-activity":
		if !s.lock.Locked {
			s.lock.LastActivity = boot
		}
		return true, nil // activity never rewrites persistent flash state
	case "lock-now", "lock-unlock":
		previous := s.lock
		if v.Get("cmd") == "lock-now" && !s.lock.Locked {
			s.advanceFavoriteLocked(time.Now())
		}
		s.lock.Locked = v.Get("cmd") == "lock-now"
		s.lock.LastActivity = boot
		s.lock.Generation++
		if e := s.persistLockLocked(); e != nil {
			s.lock = previous
			return true, e
		}
		return true, nil
	case "lock-idle":
		n, e := integer(v, "seconds", 0, 1800)
		if e != nil || !validIdle(n) {
			return true, errors.New("请选择有效的自动锁屏时间")
		}
		previous := s.cfg.Lock
		s.cfg.Lock.IdleSeconds = n
		s.lock.LastActivity = boot
		if e = s.saveLocked(); e != nil {
			s.cfg.Lock = previous
		}
		return true, e
	case "lock-powered-multiplier":
		n, e := integer(v, "times", 2, 10)
		if e != nil || !validPoweredMultiplier(n) {
			return true, errors.New("请选择 2、3、5 或 10 倍")
		}
		old := s.cfg.Lock.PoweredMultiplier
		s.cfg.Lock.PoweredMultiplier = n
		if e = s.saveLocked(); e != nil {
			s.cfg.Lock.PoweredMultiplier = old
			return true, e
		}
		s.lock.LastActivity = boot
		return true, nil
	case "wallpaper-refresh":
		if !s.net.Connected || s.cfg.Airplane {
			return true, errors.New("请先连接 Wi-Fi；离线时继续使用缓存")
		}
		go s.refreshSpotlight()
		return true, nil
	case "wallpaper-favorite", "wallpaper-mode", "wallpaper-use":
		return true, s.galleryCommandLocked(v)
	}
	return false, nil
}
func (s *Service) publishLockLocked(b *strings.Builder) {
	fmt.Fprintf(b, "lock\t%t\t%d\t%d\n", s.lock.Locked, s.cfg.Lock.IdleSeconds, s.lock.Generation)
	fmt.Fprintf(b, "power\t%t\t%t\t%d\t%d\n", s.supply.Known, s.supply.Powered, s.poweredMultiplierLocked(), s.effectiveIdleLocked())
	path, title, credit := "", "", ""
	for _, im := range s.galleryImagesLocked() {
		if im.ID == s.spotlight.Current {
			path, title, credit = s.photoPath(im.ID), im.Title, im.Copyright
			break
		}
	}
	fmt.Fprintf(b, "wallpaper\t%s\t%s\t%s\t%d\t%t\t%s\n", field(path), field(title), field(credit), len(s.spotlight.Entries), s.spotlightBusy, field(s.spotlightMessage))
	s.publishGalleryLocked(b)
}

// Microsoft does not publish a supported wallpaper API. The endpoint and nested
// item format were documented by ORelio/Spotlight-Downloader (SpotlightAPI.md).
// This implementation is independent and only downloads the image and its credit;
// no advertising, impression, or click-tracking requests are sent.
func spotlightURLAllowed(u *url.URL) bool {
	if u.Scheme != "https" || u.User != nil || (u.Port() != "" && u.Port() != "443") {
		return false
	}
	return u.Hostname() == "fd.api.iris.microsoft.com" || u.Hostname() == "res.public.onecdn.static.microsoft"
}
func (s *Service) spotlightGet(ctx context.Context, address string, limit int64) ([]byte, error) {
	u, e := url.Parse(address)
	if e != nil || !spotlightURLAllowed(u) {
		return nil, errors.New("unexpected Spotlight image host")
	}
	req, e := http.NewRequestWithContext(ctx, "GET", address, nil)
	if e != nil {
		return nil, e
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 PaperOS/1.0")
	base := s.httpClient
	if base == nil {
		base = &http.Client{Timeout: 25 * time.Second}
	}
	client := *base
	client.CheckRedirect = func(req *http.Request, via []*http.Request) error {
		if len(via) >= 3 || !spotlightURLAllowed(req.URL) {
			return errors.New("unexpected Spotlight redirect")
		}
		return nil
	}
	r, e := client.Do(req)
	if e != nil {
		return nil, e
	}
	defer r.Body.Close()
	if r.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Spotlight HTTP %d", r.StatusCode)
	}
	b, e := io.ReadAll(io.LimitReader(r.Body, limit+1))
	if e == nil && int64(len(b)) > limit {
		e = errors.New("Spotlight response too large")
	}
	return b, e
}
func parseSpotlight(b []byte) ([]SpotlightImage, error) {
	var response struct {
		Batch struct {
			Items []struct {
				Item string `json:"item"`
			} `json:"items"`
		} `json:"batchrsp"`
	}
	if e := json.Unmarshal(b, &response); e != nil {
		return nil, e
	}
	seen := map[string]bool{}
	var result []SpotlightImage
	for _, item := range response.Batch.Items {
		var creative struct {
			Ad struct {
				Portrait struct {
					Asset string `json:"asset"`
				} `json:"portraitImage"`
				Title, Copyright string
			} `json:"ad"`
		}
		if json.Unmarshal([]byte(item.Item), &creative) != nil {
			continue
		}
		ad := creative.Ad
		u, e := url.Parse(ad.Portrait.Asset)
		if e != nil || !spotlightURLAllowed(u) || u.Hostname() == "fd.api.iris.microsoft.com" || !strings.HasSuffix(strings.ToLower(u.Path), ".jpg") || seen[ad.Portrait.Asset] {
			continue
		}
		seen[ad.Portrait.Asset] = true
		h := sha256.Sum256([]byte(ad.Portrait.Asset))
		result = append(result, SpotlightImage{ID: hex.EncodeToString(h[:]), URL: ad.Portrait.Asset, Title: clean(ad.Title, 60), Copyright: clean(ad.Copyright, 100)})
		if len(result) == 4 {
			break
		}
	}
	if len(result) == 0 {
		return nil, errors.New("Spotlight returned no portrait photographs")
	}
	return result, nil
}

func spotlightPGM(b []byte) ([]byte, error) {
	config, _, e := image.DecodeConfig(bytes.NewReader(b))
	if e != nil {
		return nil, e
	}
	if config.Width < 100 || config.Height < 100 || config.Width > 8192 || config.Height > 8192 || int64(config.Width)*int64(config.Height) > 20_000_000 {
		return nil, errors.New("unexpected Spotlight dimensions")
	}
	source, _, e := image.Decode(bytes.NewReader(b))
	if e != nil {
		return nil, e
	}
	// Centre crop to the screen aspect ratio, area-average while downsampling,
	// then ordered-dither to the panel's sixteen gray levels. No runtime library.
	w, h := source.Bounds().Dx(), source.Bounds().Dy()
	cw, ch := w, h
	if w*800 > h*600 {
		cw = h * 600 / 800
	} else {
		ch = w * 800 / 600
	}
	ox, oy := (w-cw)/2+source.Bounds().Min.X, (h-ch)/2+source.Bounds().Min.Y
	result := make([]byte, len(lockPGMHeader)+600*800)
	copy(result, lockPGMHeader)
	bayer := [4][4]int{{0, 8, 2, 10}, {12, 4, 14, 6}, {3, 11, 1, 9}, {15, 7, 13, 5}}
	for y := 0; y < 800; y++ {
		for x := 0; x < 600; x++ {
			x0, y0 := ox+x*cw/600, oy+y*ch/800
			x1, y1 := ox+(x+1)*cw/600, oy+(y+1)*ch/800
			if x1 <= x0 {
				x1 = x0 + 1
			}
			if y1 <= y0 {
				y1 = y0 + 1
			}
			sum, count := 0, 0
			for sy := y0; sy < y1; sy++ {
				for sx := x0; sx < x1; sx++ {
					sum += int(color.GrayModel.Convert(source.At(sx, sy)).(color.Gray).Y)
					count++
				}
			}
			gray := sum / count
			level := gray / 17
			if (gray%17)*16 > bayer[y&3][x&3]*17 && level < 15 {
				level++
			}
			result[len(lockPGMHeader)+y*600+x] = byte(level * 17)
		}
	}
	return result, nil
}

func (s *Service) installSpotlight(im SpotlightImage, data []byte, now time.Time) error {
	pgm, e := spotlightPGM(data)
	if e != nil {
		return e
	}
	h := sha256.Sum256(pgm)
	im.SHA256 = hex.EncodeToString(h[:])
	im.Added = now.Unix()
	if !validPhotoID(im.ID) {
		return errors.New("invalid Spotlight identifier")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, old := range s.galleryImagesLocked() {
		if old.ID == im.ID || old.SHA256 == im.SHA256 {
			return nil
		}
	}
	if e = atomicWrite(s.photoPath(im.ID), pgm, 0600); e != nil {
		return e
	}
	if e = s.writeThumbnail(im.ID, pgm); e != nil {
		_ = os.Remove(s.photoPath(im.ID))
		return e
	}
	previous := cloneGallery(s.spotlight)
	s.spotlight.Entries = append(append([]SpotlightImage(nil), s.spotlight.Entries...), im)
	removed := ""
	if len(s.spotlight.Entries) > spotlightLimit {
		index := 0
		if s.spotlight.Entries[index].ID == s.spotlight.Current {
			index++
		}
		removed = s.spotlight.Entries[index].ID
		s.spotlight.Entries = append(s.spotlight.Entries[:index], s.spotlight.Entries[index+1:]...)
	}
	s.choosePhotoLocked(now, false)
	if e = s.saveSpotlightLocked(); e != nil {
		s.spotlight = previous
		_ = os.Remove(s.photoPath(im.ID))
		_ = os.Remove(s.thumbPath(im.ID))
		return e
	}
	if removed != "" {
		s.pruneSpotlightLocked()
	}
	return nil
}
func (s *Service) pollSpotlight(now time.Time) {
	s.mu.Lock()
	due := !s.simulate && !s.sleep.Busy && s.net.Connected && !s.cfg.Airplane && !s.spotlightBusy && !now.Before(s.spotlightNext) && (s.spotlight.UpdatedDay != now.In(china).Format("2006-01-02") || len(s.spotlight.Entries) < spotlightLimit)
	s.mu.Unlock()
	if due {
		go s.refreshSpotlight()
	}
}
func (s *Service) refreshSpotlight() {
	s.mu.Lock()
	if s.spotlightBusy || s.sleep.Busy {
		s.mu.Unlock()
		return
	}
	s.spotlightBusy = true
	s.spotlightMessage = "正在缓存 Windows 聚焦图片…"
	s.mu.Unlock()
	if s.run != "" {
		s.publish()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	now := time.Now()
	var lastError error
	okay := false
	markets := [][2]string{{"CN", "zh-CN"}, {"US", "en-US"}, {"GB", "en-GB"}, {"DE", "de-DE"}}
	for _, market := range markets {
		address := spotlightEndpoint + "?placement=88000820&bcnt=4&fmt=json&country=" + market[0] + "&locale=" + market[1]
		b, e := s.spotlightGet(ctx, address, 1<<20)
		if e != nil {
			lastError = e
			continue
		}
		images, e := parseSpotlight(b)
		if e != nil {
			lastError = e
			continue
		}
		for _, im := range images {
			s.mu.Lock()
			exists := false
			for _, old := range s.galleryImagesLocked() {
				if old.ID == im.ID {
					exists = true
					break
				}
			}
			s.mu.Unlock()
			if exists {
				okay = true
				continue
			}
			data, e := s.spotlightGet(ctx, im.URL, 8<<20)
			if e == nil {
				e = s.installSpotlight(im, data, now)
			}
			if e != nil {
				lastError = e
			} else {
				okay = true
			}
		}
		s.mu.Lock()
		count := len(s.spotlight.Entries)
		s.mu.Unlock()
		if count == spotlightLimit || ctx.Err() != nil {
			break
		}
	}
	s.mu.Lock()
	s.spotlightBusy = false
	s.spotlightNext = time.Now().Add(30 * time.Minute)
	if okay {
		s.spotlight.UpdatedDay = now.In(china).Format("2006-01-02")
		s.spotlightMessage = fmt.Sprintf("Windows 聚焦 · 已缓存 %d/7 张", len(s.spotlight.Entries))
		_ = s.saveSpotlightLocked()
	} else {
		s.spotlightMessage = "暂时无法更新，联网后重试；保留已有图片"
		if lastError != nil {
			log.Printf("Spotlight refresh: %v", lastError)
		}
	}
	s.pruneSpotlightLocked()
	s.mu.Unlock()
	if s.run != "" {
		s.publish()
	}
}

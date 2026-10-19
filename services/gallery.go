package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"log"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const favoriteLimit = 64

func cloneGallery(c SpotlightCache) SpotlightCache {
	c.Entries = append([]SpotlightImage(nil), c.Entries...)
	c.Favorites = append([]SpotlightImage(nil), c.Favorites...)
	if c.Fixed != nil {
		fixed := *c.Fixed
		c.Fixed = &fixed
	}
	return c
}
func (s *Service) thumbPath(id string) string { return filepath.Join(s.cacheDir(), id+".thumb.pgm") }
func (s *Service) writeThumbnail(id string, pgm []byte) error {
	if !validPhotoID(id) || len(pgm) != len(lockPGMHeader)+600*800 || !bytes.HasPrefix(pgm, []byte(lockPGMHeader)) {
		return errors.New("invalid wallpaper thumbnail source")
	}
	thumb := make([]byte, len(lockThumbHeader)+150*200)
	copy(thumb, lockThumbHeader)
	for y := 0; y < 200; y++ {
		for x := 0; x < 150; x++ {
			sum := 0
			for dy := 0; dy < 4; dy++ {
				for dx := 0; dx < 4; dx++ {
					sum += int(pgm[len(lockPGMHeader)+(y*4+dy)*600+x*4+dx])
				}
			}
			thumb[len(lockThumbHeader)+y*150+x] = byte(((sum/16 + 8) / 17) * 17)
		}
	}
	if previous, e := os.ReadFile(s.thumbPath(id)); e == nil && bytes.Equal(previous, thumb) {
		return nil
	}
	return atomicWrite(s.thumbPath(id), thumb, 0600)
}
func (s *Service) loadGallery(c SpotlightCache) {
	s.spotlight = c
	s.spotlight.Entries = nil
	s.spotlight.Favorites = nil
	s.spotlight.Fixed = nil
	validated := map[string]SpotlightImage{}
	validate := func(im SpotlightImage) (SpotlightImage, bool) {
		if !validPhotoID(im.ID) || !validPhotoID(im.SHA256) {
			return im, false
		}
		if known, okay := validated[im.ID]; okay {
			return known, true
		}
		info, e := os.Stat(s.photoPath(im.ID))
		if e != nil || info.Size() != int64(len(lockPGMHeader)+600*800) {
			return im, false
		}
		data, e := os.ReadFile(s.photoPath(im.ID))
		if e != nil || !bytes.HasPrefix(data, []byte(lockPGMHeader)) {
			return im, false
		}
		h := sha256.Sum256(data)
		if hex.EncodeToString(h[:]) != im.SHA256 {
			return im, false
		}
		if e = s.writeThumbnail(im.ID, data); e != nil {
			log.Printf("wallpaper thumbnail: %v", e)
		}
		validated[im.ID] = im
		return im, true
	}
	load := func(from []SpotlightImage, limit int) []SpotlightImage {
		var to []SpotlightImage
		seen := map[string]bool{}
		for _, im := range from {
			if len(to) == limit {
				break
			}
			if seen[im.ID] {
				continue
			}
			if im, okay := validate(im); okay {
				seen[im.ID] = true
				to = append(to, im)
			}
		}
		return to
	}
	s.spotlight.Entries = load(c.Entries, spotlightLimit)
	s.spotlight.Favorites = load(c.Favorites, favoriteLimit)
	if c.Fixed != nil {
		if im, okay := validate(*c.Fixed); okay {
			s.spotlight.Fixed = &im
		}
	}
	if c.Mode != "daily" && c.Mode != "favorites" && c.Mode != "fixed" {
		s.spotlight.Mode = "daily"
	}
	if s.spotlight.Mode == "favorites" && len(s.spotlight.Favorites) == 0 {
		s.spotlight.Mode = "daily"
	}
	if s.spotlight.Mode == "fixed" && s.spotlight.Fixed == nil {
		s.spotlight.Mode = "daily"
	}
}
func (s *Service) galleryImagesLocked() []SpotlightImage {
	var result []SpotlightImage
	seen := map[string]bool{}
	add := func(im SpotlightImage) {
		if !seen[im.ID] {
			seen[im.ID] = true
			result = append(result, im)
		}
	}
	for _, im := range s.spotlight.Entries {
		add(im)
	}
	for _, im := range s.spotlight.Favorites {
		add(im)
	}
	if s.spotlight.Fixed != nil {
		add(*s.spotlight.Fixed)
	}
	return result
}
func (s *Service) galleryFindLocked(id string) (SpotlightImage, bool) {
	if validPhotoID(id) {
		for _, im := range s.galleryImagesLocked() {
			if im.ID == id {
				return im, true
			}
		}
	}
	return SpotlightImage{}, false
}
func photoIndex(images []SpotlightImage, id string) int {
	for i, im := range images {
		if im.ID == id {
			return i
		}
	}
	return -1
}
func (s *Service) choosePhotoLocked(now time.Time, advance bool) bool {
	before, day, mode := s.spotlight.Current, s.spotlight.Day, s.spotlight.Mode
	if s.spotlight.Mode == "fixed" && s.spotlight.Fixed != nil {
		s.spotlight.Current = s.spotlight.Fixed.ID
		return before != s.spotlight.Current
	}
	pool := s.spotlight.Entries
	if s.spotlight.Mode == "favorites" {
		pool = s.spotlight.Favorites
		if len(pool) == 0 {
			s.spotlight.Mode = "daily"
			pool = s.spotlight.Entries
		}
	}
	if len(pool) == 0 {
		pool = s.galleryImagesLocked()
	}
	if len(pool) == 0 {
		s.spotlight.Current = ""
		return before != "" || mode != s.spotlight.Mode
	}
	index := photoIndex(pool, s.spotlight.Current)
	today := now.In(china).Format("2006-01-02")
	if index >= 0 && !advance && (s.spotlight.Mode == "favorites" || s.spotlight.Day == today) {
		return mode != s.spotlight.Mode
	}
	if index < 0 {
		index = 0
	} else {
		index = (index + 1) % len(pool)
	}
	s.spotlight.Current, s.spotlight.Day = pool[index].ID, today
	return before != s.spotlight.Current || day != s.spotlight.Day || mode != s.spotlight.Mode
}
func (s *Service) advanceFavoriteLocked(now time.Time) {
	if s.spotlight.Mode != "favorites" {
		return
	}
	previous := s.spotlight // Choosing another photo does not modify either image slice.
	if s.choosePhotoLocked(now, true) {
		if e := s.saveSpotlightLocked(); e != nil {
			s.spotlight = previous
			log.Printf("favorite rotation: %v", e)
		}
	}
}
func (s *Service) galleryCommandLocked(v url.Values) error {
	previous := cloneGallery(s.spotlight)
	message := ""
	switch v.Get("cmd") {
	case "wallpaper-favorite":
		im, okay := s.galleryFindLocked(v.Get("id"))
		if !okay {
			return errors.New("这张图片已更新，请返回壁纸列表重选")
		}
		if v.Get("enabled") != "true" && v.Get("enabled") != "false" {
			return errors.New("请选择收藏或取消收藏")
		}
		index := photoIndex(s.spotlight.Favorites, im.ID)
		if v.Get("enabled") == "true" {
			if index >= 0 {
				return nil
			}
			if len(s.spotlight.Favorites) >= favoriteLimit {
				return fmt.Errorf("最多收藏 %d 张，请先取消部分收藏", favoriteLimit)
			}
			s.spotlight.Favorites = append(s.spotlight.Favorites, im)
			message = "已收藏，更新缓存时会保留"
		} else {
			if index < 0 {
				return nil
			}
			s.spotlight.Favorites = append(s.spotlight.Favorites[:index], s.spotlight.Favorites[index+1:]...)
			message = "已取消收藏"
			if s.spotlight.Mode == "favorites" && len(s.spotlight.Favorites) == 0 {
				s.spotlight.Mode = "daily"
				message = "已取消收藏；暂无收藏，恢复每日换图"
			}
		}
	case "wallpaper-use":
		im, okay := s.galleryFindLocked(v.Get("id"))
		if !okay {
			return errors.New("这张图片已更新，请返回壁纸列表重选")
		}
		s.spotlight.Fixed = &im
		s.spotlight.Mode = "fixed"
		message = "已设为固定壁纸，不再自动更换"
	case "wallpaper-mode":
		mode := v.Get("mode")
		if mode != "daily" && mode != "favorites" && mode != "fixed" {
			return errors.New("请选择有效的壁纸模式")
		}
		if mode == "favorites" && len(s.spotlight.Favorites) == 0 {
			return errors.New("请先在壁纸预览中收藏图片")
		}
		if mode == "fixed" && s.spotlight.Fixed == nil {
			im, okay := s.galleryFindLocked(s.spotlight.Current)
			if !okay {
				return errors.New("请先缓存或选择一张壁纸")
			}
			s.spotlight.Fixed = &im
		}
		s.spotlight.Mode = mode
	}
	s.choosePhotoLocked(time.Now(), false)
	if e := s.saveSpotlightLocked(); e != nil {
		s.spotlight = previous
		return e
	}
	s.message = message
	s.pruneSpotlightLocked()
	return nil
}
func (s *Service) publishGalleryLocked(b *strings.Builder) {
	if s.spotlight.Revision == 0 {
		s.spotlight.Revision = 1
	}
	path := filepath.Join(s.run, "wallpapers.tsv")
	fixed := ""
	if s.spotlight.Fixed != nil {
		fixed = s.spotlight.Fixed.ID
	}
	if s.galleryPublished != s.spotlight.Revision {
		var catalog strings.Builder
		fmt.Fprintf(&catalog, "paperos-wallpapers-v1\t%d\n", s.spotlight.Revision)
		for _, im := range s.galleryImagesLocked() {
			fmt.Fprintf(&catalog, "photo\t%s\t%s\t%s\t%s\t%t\t%t\t%t\n", im.ID, field(s.photoPath(im.ID)), field(im.Title), field(im.Copyright), photoIndex(s.spotlight.Entries, im.ID) >= 0, photoIndex(s.spotlight.Favorites, im.ID) >= 0, im.ID == fixed)
		}
		if e := atomicWrite(path, []byte(catalog.String()), 0600); e == nil {
			s.galleryPublished = s.spotlight.Revision
		} else {
			log.Printf("wallpaper catalog: %v", e)
		}
	}
	mode := s.spotlight.Mode
	if mode == "" {
		mode = "daily"
	}
	fmt.Fprintf(b, "gallery\t%s\t%d\t%s\t%s\t%s\t%d\n", mode, len(s.spotlight.Favorites), field(s.spotlight.Current), field(fixed), field(path), s.spotlight.Revision)
}

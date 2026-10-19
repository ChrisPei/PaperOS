package main

import (
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestVersionOneGalleryMigratesWithoutChangingPhotoAndRepairsThumbnail(t *testing.T) {
	s := testService(t)
	now := time.Now()
	for i := 1; i <= 3; i++ {
		addLockPhoto(t, s, i, now)
	}
	previous := SpotlightCache{Version: 1, Day: s.spotlight.Day, Current: s.spotlight.Current,
		UpdatedDay: s.spotlight.UpdatedDay, Entries: s.spotlight.Entries}
	index, e := json.Marshal(previous)
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(s.cacheDir(), "index.json"), index, 0600); e != nil {
		t.Fatal(e)
	}
	id := lockPhoto(2).ID
	photo, e := os.ReadFile(s.photoPath(id))
	if e != nil {
		t.Fatal(e)
	}
	if e = os.Remove(s.thumbPath(id)); e != nil {
		t.Fatal(e)
	}
	restarted := testService(t)
	restarted.root = s.root
	restarted.loadLock()
	migrated, e := os.ReadFile(filepath.Join(s.cacheDir(), "index.json"))
	if e != nil {
		t.Fatal(e)
	}
	var current SpotlightCache
	if e = json.Unmarshal(migrated, &current); e != nil {
		t.Fatal(e)
	}
	if current.Version != 2 || current.Mode != "daily" || current.Current != previous.Current || len(current.Entries) != 3 {
		t.Fatal("old cache was not migrated with its current photo intact")
	}
	if info, e := os.Stat(restarted.thumbPath(id)); e != nil || info.Size() != 30015 {
		t.Fatal("missing thumbnail was not repaired")
	}
	retained, e := os.ReadFile(restarted.photoPath(id))
	if e != nil || string(retained) != string(photo) {
		t.Fatal("migration changed the full photograph")
	}
}

func TestFavoriteAndFixedPhotosSurviveCacheEvictionAndRestart(t *testing.T) {
	s := testService(t)
	now := time.Now()
	for i := 1; i <= 7; i++ {
		addLockPhoto(t, s, i, now)
	}
	mustCommand(t, s, "wallpaper-favorite", "id", lockPhoto(2).ID, "enabled", "true")
	mustCommand(t, s, "wallpaper-use", "id", lockPhoto(3).ID)
	mustCommand(t, s, "wallpaper-mode", "mode", "daily")
	s.selectPhotoLocked(now.AddDate(0, 0, 1))
	for i := 8; i <= 14; i++ {
		addLockPhoto(t, s, i, now.AddDate(0, 0, 1))
	}
	if len(s.spotlight.Entries) != 7 || photoIndex(s.spotlight.Entries, lockPhoto(2).ID) >= 0 || photoIndex(s.spotlight.Entries, lockPhoto(3).ID) >= 0 {
		t.Fatal("fixture did not evict the saved photographs from recent cache")
	}
	for _, id := range []string{lockPhoto(2).ID, lockPhoto(3).ID} {
		if _, e := os.Stat(s.photoPath(id)); e != nil {
			t.Fatal("saved photograph was deleted", e)
		}
		if _, e := os.Stat(s.thumbPath(id)); e != nil {
			t.Fatal("saved thumbnail was deleted", e)
		}
	}
	restarted := testService(t)
	restarted.root = s.root
	restarted.loadLock()
	if len(restarted.spotlight.Favorites) != 1 || restarted.spotlight.Fixed == nil {
		t.Fatal("saved selection did not survive backend restart")
	}
	mustCommand(t, restarted, "wallpaper-mode", "mode", "fixed")
	restarted.selectPhotoLocked(now.AddDate(0, 0, 100))
	if restarted.spotlight.Current != lockPhoto(3).ID {
		t.Fatal("fixed image changed after calendar advance")
	}
	mustCommand(t, restarted, "wallpaper-favorite", "id", lockPhoto(2).ID, "enabled", "false")
	if _, e := os.Stat(restarted.photoPath(lockPhoto(2).ID)); !os.IsNotExist(e) {
		t.Fatal("unfavorited photo outside recent cache was not removed")
	}
	if _, e := os.Stat(restarted.photoPath(lockPhoto(3).ID)); e != nil {
		t.Fatal("removing another favorite deleted the fixed photo")
	}
}
func TestFavoriteRotationOccursOncePerLockAndNeverOnDailyTick(t *testing.T) {
	s := testService(t)
	now := time.Now()
	if e := s.galleryCommandLocked(url.Values{"cmd": {"wallpaper-mode"}, "mode": {"favorites"}}); e == nil {
		t.Fatal("empty favorite rotation accepted")
	}
	for i := 1; i <= 3; i++ {
		addLockPhoto(t, s, i, now)
	}
	for i := 1; i <= 2; i++ {
		mustCommand(t, s, "wallpaper-favorite", "id", lockPhoto(i).ID, "enabled", "true")
	}
	mustCommand(t, s, "wallpaper-mode", "mode", "favorites")
	current := s.spotlight.Current
	s.selectPhotoLocked(now.AddDate(0, 0, 10))
	if s.spotlight.Current != current {
		t.Fatal("favorite mode changed on daily tick")
	}
	mustCommand(t, s, "lock-now")
	rotated := s.spotlight.Current
	if rotated == current {
		t.Fatal("entering lock did not advance the favorite")
	}
	mustCommand(t, s, "lock-now")
	if s.spotlight.Current != rotated {
		t.Fatal("repeated lock command rotated twice")
	}
	mustCommand(t, s, "lock-unlock")
	mustCommand(t, s, "lock-now")
	if s.spotlight.Current != current {
		t.Fatal("next lock did not return to the next favorite")
	}
	for i := 1; i <= 2; i++ {
		mustCommand(t, s, "wallpaper-favorite", "id", lockPhoto(i).ID, "enabled", "false")
	}
	if s.spotlight.Mode != "daily" {
		t.Fatal("removing the last favorite left an empty rotation")
	}
}
func TestGalleryCatalogIsReadOnlyDuringPreviewAndDoesNotDuplicateFavorites(t *testing.T) {
	s := testService(t)
	now := time.Now()
	addLockPhoto(t, s, 1, now)
	mustCommand(t, s, "wallpaper-favorite", "id", lockPhoto(1).ID, "enabled", "true")
	s.publish()
	before, e := os.ReadFile(filepath.Join(s.cacheDir(), "index.json"))
	if e != nil {
		t.Fatal(e)
	}
	catalog, e := os.ReadFile(filepath.Join(s.run, "wallpapers.tsv"))
	if e != nil {
		t.Fatal(e)
	}
	if strings.Count(string(catalog), "\nphoto\t") != 1 || !strings.Contains(string(catalog), "\ttrue\ttrue\tfalse\n") {
		t.Fatal("recent and favorite copies were not merged in the gallery")
	}
	if info, e := os.Stat(s.thumbPath(lockPhoto(1).ID)); e != nil || info.Size() != 30015 {
		t.Fatal("thumbnail has incorrect display dimensions")
	}
	for i := 0; i < 5; i++ {
		s.publish()
		_, _ = os.ReadFile(filepath.Join(s.run, "wallpapers.tsv"))
	}
	after, _ := os.ReadFile(filepath.Join(s.cacheDir(), "index.json"))
	if string(before) != string(after) {
		t.Fatal("reading gallery previews rewrote persistent preferences")
	}
}

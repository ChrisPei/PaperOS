package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

func (s *Service) storePluginDirectory(id string) string {
	return filepath.Join(s.apps, ".data", "org.paperos.koreader", "plugins", storeSlug(strings.TrimPrefix(id, "koplugin."))+".koplugin")
}
func (s *Service) recoverStorePlugins() {
	parent := filepath.Dir(s.storePluginDirectory("koplugin.example"))
	rows, _ := os.ReadDir(parent)
	for _, d := range rows {
		if !d.IsDir() || !strings.HasSuffix(d.Name(), ".koplugin") {
			continue
		}
		var receipt StoreReceipt
		b, e := os.ReadFile(filepath.Join(parent, d.Name(), ".paperos-store.json"))
		if e != nil || json.Unmarshal(b, &receipt) != nil || !appIDPattern.MatchString(receipt.ID) || receipt.Kind != "koplugin" {
			continue
		}
		if receipt.Directory == filepath.Join(parent, d.Name()) && receipt.Directory == s.storePluginDirectory(receipt.ID) {
			s.store.Receipts[receipt.ID] = receipt
		}
	}
}
func (s *Service) storeAppLock() (*os.File, error) {
	lock, e := os.OpenFile(filepath.Join(s.apps, ".manager.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return nil, e
	}
	if e = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); e != nil {
		lock.Close()
		return nil, errors.New("请先退出正在运行的应用，再安装或更新插件")
	}
	return lock, nil
}
func (s *Service) installStorePlugin(entry StoreEntry, payload string) error {
	lock, e := s.storeAppLock()
	if e != nil {
		return e
	}
	defer lock.Close()
	if _, e = readAppManifest(filepath.Join(s.apps, "org.paperos.koreader")); e != nil {
		return errors.New("请先安装 KOReader")
	}
	target := s.storePluginDirectory(entry.ID)
	parent := filepath.Dir(target)
	if e = os.MkdirAll(parent, 0700); e != nil {
		return e
	}
	temporary, e := os.MkdirTemp(parent, ".store-new-")
	if e != nil {
		return e
	}
	defer os.RemoveAll(temporary)
	if e = storeCopyTree(payload, temporary); e != nil {
		return e
	}
	// Common plugin configuration files contain user settings, not release code.
	// Retain them across updates; the complete previous tree is also recoverable.
	if files, e := os.ReadDir(target); e == nil {
		for _, f := range files {
			if !f.IsDir() && strings.HasSuffix(f.Name(), "_configuration.lua") {
				data, e := os.ReadFile(filepath.Join(target, f.Name()))
				if e != nil {
					return e
				}
				if len(data) > 1<<20 {
					return errors.New("插件配置文件过大")
				}
				if e = atomicWrite(filepath.Join(temporary, f.Name()), data, 0600); e != nil {
					return e
				}
			}
		}
	}
	receipt := StoreReceipt{ID: entry.ID, Key: entry.Key, Name: entry.Name, Version: entry.Version, Kind: "koplugin", Directory: target, Source: entry.SourceName}
	data, _ := json.Marshal(receipt)
	if e = atomicWrite(filepath.Join(temporary, ".paperos-store.json"), data, 0600); e != nil {
		return e
	}
	backup := filepath.Join(s.apps, ".data", "org.paperos.koreader", "store-backups", storeSlug(entry.ID)+".previous")
	if e = os.MkdirAll(filepath.Dir(backup), 0700); e != nil {
		return e
	}
	// Both paths are derived solely from a validated ID below the app data root.
	if e = os.RemoveAll(backup); e != nil {
		return e
	}
	old := false
	if _, e = os.Stat(target); e == nil {
		if e = os.Rename(target, backup); e != nil {
			return e
		}
		old = true
	} else if !os.IsNotExist(e) {
		return e
	}
	if e = os.Rename(temporary, target); e != nil {
		if old {
			_ = os.Rename(backup, target)
		}
		return e
	}
	return nil
}
func (s *Service) removeStorePlugin(receipt StoreReceipt) {
	err := func() error {
		lock, e := s.storeAppLock()
		if e != nil {
			return e
		}
		defer lock.Close()
		target := s.storePluginDirectory(receipt.ID)
		if target != receipt.Directory {
			return errors.New("插件记录路径无效")
		}
		backup := filepath.Join(s.apps, ".data", "org.paperos.koreader", "store-backups", storeSlug(receipt.ID)+".removed")
		if e = os.MkdirAll(filepath.Dir(backup), 0700); e != nil {
			return e
		}
		if e = os.RemoveAll(backup); e != nil {
			return e
		}
		if e = os.Rename(target, backup); e != nil && !os.IsNotExist(e) {
			return e
		}
		return nil
	}()
	s.mu.Lock()
	defer s.mu.Unlock()
	s.store.Busy = false
	if err != nil {
		s.store.Message = err.Error()
	} else {
		delete(s.store.Receipts, receipt.ID)
		s.store.Message = "插件已卸载；配置、数据和上一版本已保留"
	}
	s.syncStoreInstalledLocked()
	s.storeChangedLocked()
	_ = s.saveStoreLocked()
}

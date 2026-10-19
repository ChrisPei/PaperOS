package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"path"
	"sort"
	"strconv"
	"strings"
)

func storeResolveURL(base, reference string) string {
	b, e := url.Parse(base)
	if e != nil {
		return ""
	}
	r, e := url.Parse(reference)
	if e != nil {
		return ""
	}
	return b.ResolveReference(r).String()
}
func storeString(m map[string]json.RawMessage, key string) string {
	var s string
	_ = json.Unmarshal(m[key], &s)
	return s
}
func storeVersionJSON(raw json.RawMessage) string {
	var text string
	if json.Unmarshal(raw, &text) == nil {
		return text
	}
	var numbers []int
	if json.Unmarshal(raw, &numbers) == nil {
		var out []string
		for _, n := range numbers {
			out = append(out, strconv.Itoa(n))
		}
		return strings.Join(out, ".")
	}
	return ""
}
func storePlatformReason(platforms []string) string {
	if len(platforms) == 0 {
		return ""
	}
	accepted := false
	for _, platform := range platforms {
		switch strings.ToLower(platform) {
		case "paperos", "kt3", "armel", "armv7-softfloat", "kindlepw2", "kindleany", "kindle", "koreader", "linux":
			accepted = true
		}
	}
	if !accepted {
		return "这个包没有本机 ARM soft-float 版本"
	}
	return ""
}
func parseStoreCatalog(data []byte, source StoreSource) ([]StoreEntry, error) {
	var object map[string]json.RawMessage
	if e := json.Unmarshal(data, &object); e != nil {
		var rows []map[string]json.RawMessage
		if json.Unmarshal(data, &rows) != nil {
			return nil, errors.New("无法识别应用源格式")
		}
		var entries []StoreEntry
		for _, row := range rows {
			id := storeString(row, "uri")
			if id == "" {
				continue
			}
			entry := StoreEntry{ID: "kindleforge." + storeSlug(id), Name: storeString(row, "name"), Description: storeString(row, "description"), Version: "旧目录", Kind: "auto", Reason: "旧版 KindleForge 条目仅提供安装脚本，需要单独适配"}
			entries = append(entries, entry)
		}
		return normalizeStoreEntries(entries, source)
	}
	if schema := storeString(object, "schema"); schema == "paperos-store-v1" {
		var entries []StoreEntry
		if e := json.Unmarshal(object["packages"], &entries); e != nil {
			return nil, e
		}
		for i := range entries {
			if entries[i].Version == "" || entries[i].SHA256 == "" {
				return nil, errors.New("PaperOS 应用源缺少版本或 SHA-256")
			}
		}
		return normalizeStoreEntries(entries, source)
	}
	var kpm map[string]map[string]json.RawMessage
	if json.Unmarshal(object["packages"], &kpm) == nil && kpm != nil {
		var entries []StoreEntry
		for id, row := range kpm {
			var artifacts []struct {
				URL       string          `json:"url"`
				Version   json.RawMessage `json:"version"`
				Platforms []string        `json:"supported_platforms"`
				SHA256    string          `json:"sha256"`
			}
			if json.Unmarshal(row["artifacts"], &artifacts) != nil {
				continue
			}
			var best *StoreEntry
			for _, a := range artifacts {
				e := StoreEntry{ID: id, Name: storeString(row, "name"), Description: storeString(row, "description"), Kind: "auto", Version: storeVersionJSON(a.Version), URL: a.URL, SHA256: a.SHA256, Platforms: a.Platforms, Reason: storePlatformReason(a.Platforms)}
				if best == nil || (e.Reason == "" && best.Reason != "") || (e.Reason == best.Reason && storeVersionCompare(e.Version, best.Version) > 0) {
					copy := e
					best = &copy
				}
			}
			if best != nil {
				entries = append(entries, *best)
			}
		}
		return normalizeStoreEntries(entries, source)
	}
	// ZenPM native repository contract (schema_version, repo, packages array).
	var zen []map[string]json.RawMessage
	if json.Unmarshal(object["packages"], &zen) == nil && zen != nil {
		var entries []StoreEntry
		for _, row := range zen {
			var platforms []string
			_ = json.Unmarshal(row["platforms"], &platforms)
			id := storeString(row, "id")
			kind := storeString(row, "kind")
			if kind == "" {
				kind = "auto"
				for _, p := range platforms {
					if p == "koreader" {
						kind = "koplugin"
					}
				}
			}
			entry := StoreEntry{ID: id, Name: storeString(row, "name"), Description: storeString(row, "description"), Version: storeString(row, "version"), Kind: kind, URL: storeString(row, "download_url"), VersionsURL: storeString(row, "versions_url"), Homepage: storeString(row, "source"), SHA256: storeString(row, "sha256"), Platforms: platforms, Reason: storePlatformReason(platforms)}
			if entry.Version == "" {
				entry.Version = "最新发布"
			}
			if entry.Kind == "koplugin" && !strings.HasPrefix(entry.ID, "koplugin.") {
				entry.ID = "koplugin." + storeSlug(entry.ID)
			}
			if entry.URL == "" && entry.VersionsURL == "" {
				entry.Reason = "应用源只提供安装脚本，尚未适配 PaperOS"
			}
			entries = append(entries, entry)
		}
		return normalizeStoreEntries(entries, source)
	}
	return nil, errors.New("支持 PaperOS、ZenPM、KPM v2/v3 与旧 KindleForge 目录")
}
func normalizeStoreEntries(entries []StoreEntry, source StoreSource) ([]StoreEntry, error) {
	if len(entries) > 512 {
		return nil, errors.New("应用源条目过多")
	}
	seen := map[string]bool{}
	for i := range entries {
		e := &entries[i]
		if !appIDPattern.MatchString(e.ID) || strings.Contains(e.ID, "..") || e.Name == "" || seen[e.ID] {
			return nil, errors.New("应用源包含无效或重复编号")
		}
		seen[e.ID] = true
		e.SourceID = source.ID
		e.SourceName = clean(source.Name, 40)
		e.Key = source.ID + ":" + e.ID
		if len(e.Key) > 95 {
			return nil, errors.New("应用编号过长")
		}
		e.Name = clean(e.Name, 40)
		e.Description = clean(e.Description, 160)
		e.Version = clean(e.Version, 31)
		e.Reason = clean(e.Reason, 120)
		if e.Kind == "" {
			e.Kind = "auto"
		}
		if e.Kind != "papp" && e.Kind != "koplugin" && e.Kind != "auto" {
			e.Reason = "这个条目不属于 PaperOS 应用或 KOReader 插件"
		}
		if e.Reason == "" {
			e.Reason = storePlatformReason(e.Platforms)
		}
		if e.URL != "" {
			e.URL = storeResolveURL(source.URL, e.URL)
		}
		if e.VersionsURL != "" {
			e.VersionsURL = storeResolveURL(source.URL, e.VersionsURL)
		}
		if e.SHA256 != "" {
			e.SHA256 = strings.TrimPrefix(e.SHA256, "sha256:")
			if len(e.SHA256) != 64 {
				return nil, errors.New("应用源 SHA-256 格式无效")
			}
			for _, r := range e.SHA256 {
				if !strings.ContainsRune("0123456789abcdefABCDEF", r) {
					return nil, errors.New("应用源 SHA-256 格式无效")
				}
			}
		}
		if e.Size < 0 || e.Size > storeMaxArchive {
			e.Reason = "安装包超过本机 64 MiB 限制"
		}
	}
	return entries, nil
}

type storeReleaseAsset struct {
	Name       string `json:"name"`
	URL        string `json:"url"`
	BrowserURL string `json:"browser_download_url"`
	Size       int64  `json:"size"`
	Digest     string `json:"digest"`
}
type storeRelease struct {
	Tag        string              `json:"tag_name"`
	Prerelease bool                `json:"prerelease"`
	Assets     []storeReleaseAsset `json:"assets"`
}

func (s *Service) resolveStoreEntry(ctx context.Context, entry StoreEntry) (StoreEntry, error) {
	if entry.VersionsURL != "" {
		data, e := s.storeFetch(ctx, entry.VersionsURL, 1<<20)
		if e != nil {
			return entry, e
		}
		var list struct {
			Releases []storeRelease `json:"releases"`
		}
		if json.Unmarshal(data, &list) != nil {
			return entry, errors.New("应用版本目录无效")
		}
		for _, release := range list.Releases {
			if release.Prerelease {
				continue
			}
			for _, a := range release.Assets {
				lower := strings.ToLower(a.Name)
				if strings.Contains(lower, "armhf") || strings.Contains(lower, "kindlehf") || strings.Contains(lower, "aarch64") || strings.Contains(lower, "android") || strings.Contains(lower, "macos") {
					continue
				}
				if strings.HasSuffix(lower, ".zip") || strings.HasSuffix(lower, ".tar.gz") || strings.HasSuffix(lower, ".kpkg") {
					entry.Version = release.Tag
					entry.URL = storeResolveURL(entry.VersionsURL, a.URL)
					entry.Size = a.Size
					entry.SHA256 = strings.TrimPrefix(a.Digest, "sha256:")
					return entry, nil
				}
			}
		}
		return entry, errors.New("应用源没有可用的 ARM soft-float 安装包")
	}
	u, e := url.Parse(entry.URL)
	if e != nil {
		return entry, e
	}
	if strings.EqualFold(u.Hostname(), "github.com") {
		parts := strings.Split(strings.Trim(u.Path, "/"), "/")
		if len(parts) == 2 {
			owner, repo := parts[0], strings.TrimSuffix(parts[1], ".git")
			data, err := s.storeFetch(ctx, "https://api.github.com/repos/"+url.PathEscape(owner)+"/"+url.PathEscape(repo)+"/releases/latest", 1<<20)
			if err == nil {
				var release storeRelease
				if json.Unmarshal(data, &release) == nil {
					sort.SliceStable(release.Assets, func(i, j int) bool { return release.Assets[i].Name < release.Assets[j].Name })
					for _, a := range release.Assets {
						lower := strings.ToLower(a.Name)
						if strings.Contains(lower, "source") || strings.Contains(lower, "android") || strings.Contains(lower, "armhf") || strings.Contains(lower, "macos") || strings.Contains(lower, "windows") {
							continue
						}
						if strings.HasSuffix(lower, ".zip") || strings.HasSuffix(lower, ".tar.gz") {
							entry.URL = a.BrowserURL
							entry.Version = release.Tag
							entry.Size = a.Size
							entry.SHA256 = strings.TrimPrefix(a.Digest, "sha256:")
							return entry, nil
						}
					}
				}
			}
			// Pin source archives to a commit rather than fetching a moving branch.
			data, err = s.storeFetch(ctx, "https://api.github.com/repos/"+url.PathEscape(owner)+"/"+url.PathEscape(repo)+"/commits?per_page=1", 64<<10)
			if err != nil {
				return entry, err
			}
			var commits []struct {
				SHA string `json:"sha"`
			}
			if json.Unmarshal(data, &commits) != nil || len(commits) == 0 || len(commits[0].SHA) != 40 {
				return entry, errors.New("无法确定 GitHub 源码版本")
			}
			entry.URL = "https://api.github.com/repos/" + url.PathEscape(owner) + "/" + url.PathEscape(repo) + "/zipball/" + commits[0].SHA
			entry.Version = "git:" + commits[0].SHA[:12]
			if entry.Name == "下载链接" {
				entry.Name = repo
			}
			return entry, nil
		}
	}
	if entry.URL == "" {
		return entry, fmt.Errorf("应用 %s 没有下载地址", entry.Name)
	}
	if entry.SourceID == "direct" && entry.Version == "待识别" {
		entry.Name = path.Base(u.Path)
	}
	return entry, nil
}

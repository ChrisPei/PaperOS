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
	"time"
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
				// A CPU match alone does not make Lab126 installers usable here.
				if best.Reason == "" && !storeHasPlatform(best.Platforms, "paperos") && !storeHasPlatform(best.Platforms, "koreader") {
					best.Reason = "原厂 KPM 包依赖 Kindle 服务或安装脚本，需要移植到 PaperOS"
				}
				if storeHasPlatform(best.Platforms, "koreader") {
					best.Kind = "koplugin"
					best.ID = "koplugin." + storeSlug(best.ID)
				}
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
			if kind != "papp" {
				id = storeSlug(id)
			}
			if kind == "" {
				kind = "auto"
				for _, p := range platforms {
					if p == "koreader" {
						kind = "koplugin"
					}
				}
			}
			entry := StoreEntry{ID: id, Name: storeString(row, "name"), Description: storeString(row, "description"), Version: storeString(row, "version"), Kind: kind, URL: storeString(row, "download_url"), VersionsURL: storeString(row, "versions_url"), Homepage: storeString(row, "source"), SHA256: storeString(row, "sha256"), Platforms: platforms, Reason: storePlatformReason(platforms)}
			entry.Stars = storeStarsJSON(row["stars"])
			entry.UpdatedAt = storeString(row, "published_at") // ZenPM updated_at is the scrape time.
			entry.Category = storeString(row, "category")
			entry.AssetName = storeString(row, "source_asset")
			if entry.AssetName == "" && entry.Kind == "koplugin" {
				var assets []struct {
					Name string `json:"asset"`
				}
				_ = json.Unmarshal(row["assets"], &assets)
				for _, asset := range assets {
					if strings.Contains(strings.ToLower(asset.Name), ".koplugin") {
						entry.AssetName = asset.Name
						break
					}
				}
			}
			if entry.Kind == "koplugin" {
				category, location := storeString(row, "category"), entry.VersionsURL
				switch {
				case strings.Contains(location, ".kopatch/") || category == "patches":
					entry.Kind = "kopatch"
					entry.Reason = "KOReader 用户补丁尚未接入，请使用阅读器内的插件商店"
				case strings.Contains(location, ".iconpack/") || category == "iconpacks":
					entry.Kind = "iconpack"
					entry.Reason = "此图标包的安装方式需要单独适配"
				case strings.Contains(location, "/fonts/") || category == "fonts":
					entry.Kind = "font"
					entry.Reason = "字体包的安装方式需要单独适配"
				}
			}
			if entry.Kind == "auto" && storeHasPlatform(platforms, "kindle") && !storeHasPlatform(platforms, "paperos") {
				entry.Reason = "此应用依赖原厂 Kindle 服务或安装脚本，需要移植到 PaperOS"
			}
			if entry.Version == "" {
				entry.Version = "最新发布"
			}
			if entry.Kind != "auto" && entry.Kind != "papp" && !strings.HasPrefix(entry.ID, entry.Kind+".") {
				entry.ID = entry.Kind + "." + storeSlug(entry.ID)
			}
			if entry.URL == "" && entry.Kind == "koplugin" {
				entry.URL = entry.Homepage
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
		e.Category = clean(e.Category, 31)
		e.AssetName = clean(e.AssetName, 200)
		e.UpdatedAt = storeDate(e.UpdatedAt)
		if e.Stars != nil && (*e.Stars < 0 || *e.Stars > 1000000000) {
			e.Stars = nil
		}
		if e.Stars != nil {
			e.StatsSource = clean(source.Name, 40)
		} else {
			e.StatsSource = ""
		}
		if e.Kind == "" {
			e.Kind = "auto"
		}
		if e.Kind != "papp" && e.Kind != "koplugin" && e.Kind != "auto" && e.Reason == "" {
			e.Reason = "这个条目不属于 PaperOS 应用或 KOReader 插件"
		}
		if e.Reason == "" {
			e.Reason = storePlatformReason(e.Platforms)
		}
		if e.URL != "" {
			e.URL = storeResolveURL(storeSourceBase(source), e.URL)
		}
		if e.VersionsURL != "" {
			e.VersionsURL = storeResolveURL(storeSourceBase(source), e.VersionsURL)
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
	Tag         string              `json:"tag_name"`
	Prerelease  bool                `json:"prerelease"`
	Assets      []storeReleaseAsset `json:"assets"`
	PublishedAt string              `json:"published_at"`
}

func (s *Service) resolveStoreEntry(ctx context.Context, entry StoreEntry) (StoreEntry, error) {
	if entry.Reason != "" {
		return entry, errors.New(entry.Reason)
	}
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
			for _, a := range storePreferredAssets(entry, release.Assets) {
				lower := strings.ToLower(a.Name)
				if strings.Contains(lower, "armhf") || strings.Contains(lower, "kindlehf") || strings.Contains(lower, "aarch64") || strings.Contains(lower, "android") || strings.Contains(lower, "macos") {
					continue
				}
				if strings.HasSuffix(lower, ".zip") || strings.HasSuffix(lower, ".tar.gz") || strings.HasSuffix(lower, ".kpkg") {
					if release.PublishedAt != "" {
						entry.UpdatedAt = storeDate(release.PublishedAt)
					} else if storeVersionCompare(entry.Version, release.Tag) != 0 {
						entry.UpdatedAt = ""
					}
					entry.Version = release.Tag
					entry.URL = storeResolveURL(entry.VersionsURL, a.URL)
					entry.Size = a.Size
					entry.SHA256 = strings.TrimPrefix(a.Digest, "sha256:")
					return entry, nil
				}
			}
		}
		if entry.Kind != "koplugin" || entry.Homepage == "" {
			return entry, errors.New("应用源没有可用的 ARM soft-float 安装包")
		}
		entry.URL, entry.VersionsURL, entry.Version = entry.Homepage, "", "source"
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
					for _, a := range storePreferredAssets(entry, release.Assets) {
						lower := strings.ToLower(a.Name)
						if strings.Contains(lower, "source") || strings.Contains(lower, "android") || strings.Contains(lower, "armhf") || strings.Contains(lower, "kindlehf") || strings.Contains(lower, "aarch64") || strings.Contains(lower, "macos") || strings.Contains(lower, "windows") {
							continue
						}
						if strings.HasSuffix(lower, ".zip") || strings.HasSuffix(lower, ".tar.gz") {
							entry.URL = a.URL
							if entry.URL == "" {
								entry.URL = a.BrowserURL
							}
							entry.Version = release.Tag
							entry.UpdatedAt = storeDate(release.PublishedAt)
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
				SHA    string `json:"sha"`
				Commit struct {
					Committer struct {
						Date string `json:"date"`
					} `json:"committer"`
				} `json:"commit"`
			}
			if json.Unmarshal(data, &commits) != nil || len(commits) == 0 || len(commits[0].SHA) != 40 {
				return entry, errors.New("无法确定 GitHub 源码版本")
			}
			entry.URL = "https://api.github.com/repos/" + url.PathEscape(owner) + "/" + url.PathEscape(repo) + "/zipball/" + commits[0].SHA
			entry.Version = "git:" + commits[0].SHA[:12]
			entry.UpdatedAt = storeDate(commits[0].Commit.Committer.Date)
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

func storeDate(value string) string {
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02"} {
		if t, err := time.Parse(layout, value); err == nil {
			return t.In(china).Format("2006-01-02")
		}
	}
	return ""
}

func storeStarsJSON(raw json.RawMessage) *int64 {
	var number int64
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	if json.Unmarshal(raw, &number) != nil {
		var text string
		if json.Unmarshal(raw, &text) != nil {
			return nil
		}
		var err error
		number, err = strconv.ParseInt(text, 10, 64)
		if err != nil {
			return nil
		}
	}
	if number < 0 || number > 1000000000 {
		return nil
	}
	return &number
}

func storePreferredAssets(entry StoreEntry, assets []storeReleaseAsset) []storeReleaseAsset {
	ordered := append([]storeReleaseAsset(nil), assets...)
	score := func(name string) int {
		if entry.AssetName != "" && name == entry.AssetName {
			return 2
		}
		if entry.Kind == "koplugin" && strings.Contains(strings.ToLower(name), ".koplugin") {
			return 1
		}
		return 0
	}
	sort.SliceStable(ordered, func(i, j int) bool { return score(ordered[i].Name) > score(ordered[j].Name) })
	return ordered
}

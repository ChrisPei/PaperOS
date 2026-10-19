package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/url"
	"path"
	"regexp"
	"strings"
)

const storeMaxEntries = 1024

func storePresets() []StoreSource {
	var sources []StoreSource
	_ = json.Unmarshal(defaultStoreSources, &sources)
	return sources
}

func storePreset(id string) (StoreSource, bool) {
	for _, source := range storePresets() {
		if source.ID == id {
			return source, true
		}
	}
	return StoreSource{}, false
}

// Resolve repository roots in the UI as well as explicit manifest addresses.
// Known mirrors retain their pinned public key; arbitrary repositories do not
// inherit trust from a display name or from downloaded metadata.
func storeSourceAddress(address string, simulate bool) (StoreSource, error) {
	u, err := storeURL(address, simulate)
	if err != nil {
		return StoreSource{}, err
	}
	host, p := strings.ToLower(u.Hostname()), strings.TrimSuffix(u.Path, "/")
	id := ""
	switch {
	case (host == "repo.zen-labs.org" && (p == "" || p == "/manifest.json")) || (host == "xzenlabs.github.io" && (p == "/repo" || p == "/repo/manifest.json")):
		id = "zenpm"
	case host == "repo.kindlemodding.org" && (p == "" || p == "/manifest.json" || p == "/manifest.v2.json" || p == "/manifest.v3.json"):
		id = "kpm"
	case host == "github.com":
		p = strings.TrimSuffix(strings.ToLower(p), ".git")
		if p == "/xzenlabs/repo" {
			id = "zenpm"
		}
		if p == "/kindlemodding/repo" {
			id = "kpm"
		}
		if p == "/koreader/contrib" {
			id = "koreader-contrib"
		}
		if p == "/chrispei/paperos-apps" {
			id = "paperos"
		}
	}
	for _, preset := range storePresets() {
		if address == preset.URL {
			id = preset.ID
		}
	}
	if id != "" && u.RawQuery == "" && u.Port() == "" {
		preset, _ := storePreset(id)
		preset.Enabled = true
		return preset, nil
	}
	source := StoreSource{URL: u.String(), Name: u.Hostname(), Enabled: true}
	if strings.HasSuffix(u.Path, "/") || u.Path == "" {
		u.Path = strings.TrimSuffix(u.Path, "/") + "/manifest.json"
		source.URL = u.String()
	}
	if host == "github.com" && u.RawQuery == "" {
		parts := strings.Split(strings.Trim(u.Path, "/"), "/")
		if len(parts) == 2 && parts[0] != "" && parts[1] != "" {
			repo := strings.TrimSuffix(parts[1], ".git")
			source.URL = "https://api.github.com/repos/" + url.PathEscape(parts[0]) + "/" + url.PathEscape(repo) + "/contents/manifest.json"
			source.BaseURL = "https://raw.githubusercontent.com/" + url.PathEscape(parts[0]) + "/" + url.PathEscape(repo) + "/HEAD/manifest.json"
		}
	}
	return source, nil
}

func storeSourceBase(source StoreSource) string {
	if source.BaseURL != "" {
		return source.BaseURL
	}
	return source.URL
}

func storeUnresolvedVersion(version string) bool {
	return version == "最新发布" || version == "source" || version == "latest" || version == ""
}

func storeMetadataAddresses(address string) []string {
	u, err := url.Parse(address)
	if err != nil || u.Scheme != "https" || u.Port() != "" || u.User != nil || u.RawQuery != "" {
		return []string{address}
	}
	var relative string
	if u.Hostname() == "repo.zen-labs.org" {
		relative = strings.TrimPrefix(u.Path, "/")
	}
	if u.Hostname() == "xzenlabs.github.io" && strings.HasPrefix(u.Path, "/repo/") {
		relative = strings.TrimPrefix(u.Path, "/repo/")
	}
	if relative == "" || strings.Contains(relative, "..") || strings.Contains(u.RawPath, "%") {
		return []string{address}
	}
	if strings.HasPrefix(relative, "packages/") && strings.HasSuffix(relative, "/versions.json") {
		return []string{"https://api.github.com/repos/xZenLabs/repo/contents/" + relative, address}
	}
	if relative == "manifest.json" || relative == "manifest.json.sig" {
		mirror := "https://xzenlabs.github.io/repo/" + relative
		if u.Hostname() == "xzenlabs.github.io" {
			mirror = "https://repo.zen-labs.org/" + relative
		}
		return []string{address, mirror}
	}
	return []string{address}
}

func storeHasPlatform(platforms []string, platform string) bool {
	for _, p := range platforms {
		if strings.EqualFold(p, platform) {
			return true
		}
	}
	return false
}

// Resolve a public release filename to GitHub's asset endpoint. Some e-reader
// networks cannot reach github.com downloads but can use api.github.com. Match
// the exact tag/file and retain the catalog digest rather than guessing assets.
func (s *Service) storeAssetURL(ctx context.Context, address, digest string) (string, error) {
	u, err := url.Parse(address)
	if err != nil {
		return address, err
	}
	if u.Hostname() != "github.com" {
		return address, nil
	}
	parts := strings.Split(strings.Trim(u.EscapedPath(), "/"), "/")
	if len(parts) != 6 || parts[2] != "releases" || parts[3] != "download" {
		return address, nil
	}
	for i := range parts {
		parts[i], err = url.PathUnescape(parts[i])
		if err != nil {
			return address, err
		}
	}
	metadata, err := s.storeFetch(ctx, "https://api.github.com/repos/"+url.PathEscape(parts[0])+"/"+url.PathEscape(parts[1])+"/releases/tags/"+url.PathEscape(parts[4]), 1<<20)
	if err != nil {
		return address, nil
	} // The original HTTPS download remains usable.
	var release storeRelease
	if json.Unmarshal(metadata, &release) != nil {
		return address, errors.New("GitHub 发布元数据无效")
	}
	for _, asset := range release.Assets {
		if asset.Name != parts[5] {
			continue
		}
		if digest != "" && asset.Digest != "" && !strings.EqualFold(strings.TrimPrefix(asset.Digest, "sha256:"), strings.TrimPrefix(digest, "sha256:")) {
			return address, errors.New("软件源摘要与发布者资产不一致")
		}
		if asset.URL != "" {
			return asset.URL, nil
		}
	}
	return address, nil
}

func storeRepository(value string) (string, string, bool) {
	value = strings.TrimSpace(value)
	if strings.HasPrefix(value, "git@github.com:") {
		value = "https://github.com/" + strings.TrimPrefix(value, "git@github.com:")
	}
	if strings.HasPrefix(value, "ssh://git@github.com/") {
		value = "https://github.com/" + strings.TrimPrefix(value, "ssh://git@github.com/")
	}
	u, e := url.Parse(value)
	if e != nil || u.Hostname() != "github.com" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return "", "", false
	}
	p := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(p) != 2 {
		return "", "", false
	}
	owner, repo := p[0], strings.TrimSuffix(p[1], ".git")
	valid := regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	if !valid.MatchString(owner) || !valid.MatchString(repo) || owner == "." || repo == "." || strings.Contains(owner, "..") || strings.Contains(repo, "..") {
		return "", "", false
	}
	return owner, repo, true
}

// KOReader's contrib catalog consists of Git submodule metadata and exact
// gitlinks. Only read data: no Git hooks, Lua, shell or third-party installers.
func (s *Service) fetchStoreContrib(ctx context.Context, source StoreSource, data []byte) ([]StoreEntry, error) {
	var tree struct {
		Truncated bool                               `json:"truncated"`
		Tree      []struct{ Path, Type, SHA string } `json:"tree"`
	}
	if json.Unmarshal(data, &tree) != nil || tree.Truncated || len(tree.Tree) > 1024 {
		return nil, errors.New("KOReader 社区索引无效或不完整")
	}
	u, err := url.Parse(source.URL)
	if err != nil || u.Hostname() != "api.github.com" {
		return nil, errors.New("社区索引需要 GitHub Git Tree 地址")
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(parts) < 6 || parts[0] != "repos" || parts[3] != "git" || parts[4] != "trees" {
		return nil, errors.New("社区索引地址无效")
	}
	moduleSHA := ""
	for _, row := range tree.Tree {
		if row.Path == ".gitmodules" && row.Type == "blob" {
			moduleSHA = row.SHA
		}
	}
	if !regexp.MustCompile(`^[0-9a-f]{40}$`).MatchString(moduleSHA) {
		return nil, errors.New("社区索引缺少固定版本的子模块清单")
	}
	metadata, err := s.storeFetch(ctx, "https://api.github.com/repos/"+parts[1]+"/"+parts[2]+"/git/blobs/"+moduleSHA, 256<<10)
	if err != nil {
		return nil, err
	}
	var blob struct{ Content, Encoding string }
	if json.Unmarshal(metadata, &blob) != nil || blob.Encoding != "base64" {
		return nil, errors.New("社区子模块清单无效")
	}
	modules, err := base64.StdEncoding.DecodeString(strings.ReplaceAll(blob.Content, "\n", ""))
	if err != nil {
		return nil, err
	}
	paths := map[string]string{}
	modulePath, repository := "", ""
	flush := func() {
		if modulePath != "" && repository != "" {
			paths[modulePath] = repository
		}
		modulePath, repository = "", ""
	}
	for _, line := range strings.Split(string(modules), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "[") {
			flush()
			continue
		}
		key, value, found := strings.Cut(line, "=")
		if !found {
			continue
		}
		value = strings.Trim(strings.TrimSpace(value), `"`)
		switch strings.TrimSpace(key) {
		case "path":
			modulePath = value
		case "url":
			repository = value
		}
	}
	flush()
	var entries []StoreEntry
	for _, row := range tree.Tree {
		if row.Type != "commit" || !strings.HasSuffix(row.Path, ".koplugin") || path.Base(row.Path) != row.Path {
			continue
		}
		if !regexp.MustCompile(`^[0-9a-f]{40}$`).MatchString(row.SHA) {
			return nil, errors.New("插件版本不是固定 Git 提交")
		}
		name := strings.TrimSuffix(row.Path, ".koplugin")
		entry := StoreEntry{ID: "koplugin." + storeSlug(name), Name: name, Description: "KOReader contrib 社区收录的阅读器插件。", Kind: "koplugin", Version: "git:" + row.SHA[:12], Platforms: []string{"koreader"}}
		owner, repo, okay := storeRepository(paths[row.Path])
		if !okay {
			entry.Reason = "此插件的代码托管地址需要单独适配"
		} else {
			entry.Homepage = "https://github.com/" + owner + "/" + repo
			entry.Description += " 作者：" + owner
			entry.URL = "https://api.github.com/repos/" + owner + "/" + repo + "/zipball/" + row.SHA
		}
		entries = append(entries, entry)
	}
	if len(entries) == 0 {
		return nil, errors.New("社区目录没有可识别的单插件条目")
	}
	return normalizeStoreEntries(entries, source)
}

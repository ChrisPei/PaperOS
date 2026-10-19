package main

import "strings"

func storeSortValid(mode string) bool {
	return mode == "popular" || mode == "recent" || mode == "name"
}

// Reuse a signed repository's project statistics for the very same plugin
// repository. Do not copy versions, release dates, URLs, hashes or permissions:
// contrib can intentionally pin a different revision from the latest release.
func storeEnrichStats(entries []StoreEntry, sources []StoreSource) {
	trusted := false
	preset, _ := storePreset("zenpm")
	for _, source := range sources {
		if source.ID == preset.ID && source.PublicKey == preset.PublicKey {
			trusted = true
		}
	}
	if !trusted {
		return
	}
	key := func(entry StoreEntry) string {
		owner, repo, okay := storeRepository(entry.Homepage)
		if !okay || entry.Kind != "koplugin" {
			return ""
		}
		return strings.ToLower(owner + "/" + repo)
	}
	stats := map[string]StoreEntry{}
	for _, entry := range entries {
		if entry.SourceID == preset.ID && entry.Stars != nil && key(entry) != "" {
			stats[key(entry)] = entry
		}
	}
	for i := range entries {
		entry := &entries[i]
		if entry.SourceID == preset.ID {
			continue
		}
		if other, okay := stats[key(*entry)]; okay && (entry.Stars == nil || entry.StatsSource == other.StatsSource) {
			stars := *other.Stars
			entry.Stars, entry.StatsSource = &stars, other.StatsSource
			if entry.Category == "" {
				entry.Category = other.Category
			}
		}
	}
}

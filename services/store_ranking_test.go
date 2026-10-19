package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestStorePopularityDistinguishesMissingAndZero(t *testing.T) {
	for _, raw := range []string{"null", `"not available"`, "-1", "1000000001"} {
		if storeStarsJSON(json.RawMessage(raw)) != nil {
			t.Fatal("Invalid statistic received a score", raw)
		}
	}
	for _, raw := range []string{"0", `"0"`, "624", `"624"`} {
		if value := storeStarsJSON(json.RawMessage(raw)); value == nil || (*value != 0 && *value != 624) {
			t.Fatal(raw, value)
		}
	}
}

func TestStoreRankingUsesReleaseDateNotScraperDate(t *testing.T) {
	data, err := os.ReadFile("testdata/store/zenpm.json")
	if err != nil {
		t.Fatal(err)
	}
	source, _ := storePreset("zenpm")
	entries, err := parseStoreCatalog(data, source)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.ID == "koplugin.appstore" {
			if entry.Stars == nil || *entry.Stars != 624 || entry.UpdatedAt != "2026-09-11" || entry.StatsSource != source.Name || entry.Category != "utility" {
				t.Fatal(entry)
			}
		}
		if entry.ID == "koplugin.clock" && entry.UpdatedAt != "" {
			t.Fatal("A source-only plugin was dated using the scraper timestamp", entry)
		}
	}
}

func TestStoreRankingSharedProjectStatisticsKeepVersionProvenance(t *testing.T) {
	source, _ := storePreset("zenpm")
	stars := int64(624)
	entry := StoreEntry{ID: "koplugin.appstore", Kind: "koplugin", Homepage: "https://github.com/omer-faruq/appstore.koplugin", Version: "git:aaaaaaaaaaaa", UpdatedAt: "2025-01-01", URL: "https://api.github.com/repos/omer-faruq/appstore.koplugin/zipball/" + strings.Repeat("a", 40), SourceID: "koreader-contrib"}
	reference := StoreEntry{Kind: "koplugin", Homepage: entry.Homepage, Stars: &stars, StatsSource: source.Name, Category: "utility", SourceID: source.ID, Version: "2.0", UpdatedAt: "2026-10-19", URL: "https://example.org/new.zip"}
	entries := []StoreEntry{entry, reference, {ID: entry.ID, Kind: "koplugin", Homepage: "https://github.com/other/project", SourceID: "other"}}
	storeEnrichStats(entries, []StoreSource{{ID: source.ID, PublicKey: "wrong key"}})
	if entries[0].Stars != nil {
		t.Fatal("Untrusted statistics crossed repository boundaries")
	}
	storeEnrichStats(entries, []StoreSource{source})
	if entries[0].Stars == nil || *entries[0].Stars != 624 || entries[0].Version != entry.Version || entries[0].URL != entry.URL || entries[0].UpdatedAt != entry.UpdatedAt || entries[2].Stars != nil {
		t.Fatal(entries)
	}
}

func TestStoreSortChoicePersistsAcrossRestart(t *testing.T) {
	s := storeTestService(t)
	mustCommand(t, s, "store-sort", "mode", "recent")
	s.loadStore()
	if s.store.SortMode != "recent" {
		t.Fatal("Sort choice was forgotten")
	}
	mustCommand(t, s, "store-sort", "mode", "name")
	s.loadStore()
	if s.store.SortMode != "name" {
		t.Fatal("Name sorting was forgotten")
	}
	if storeSortValid("downloads") || storeSortValid("") {
		t.Fatal("Invented or invalid ranking accepted")
	}
}

func TestStorePrefersKOReaderAssetInMultiApplicationRelease(t *testing.T) {
	assets := []storeReleaseAsset{{Name: "Readest.calibre-plugin.zip"}, {Name: "desktop-windows.zip"}, {Name: "Readest-0.12.16-1.koplugin.zip"}}
	ordered := storePreferredAssets(StoreEntry{Kind: "koplugin"}, assets)
	if ordered[0].Name != "Readest-0.12.16-1.koplugin.zip" || assets[0].Name != "Readest.calibre-plugin.zip" {
		t.Fatal("The wrong product artifact would be downloaded", ordered)
	}
}

package main

import (
	"net/http"
	"testing"
)

func TestStoreRemovedSourcesStayRemovedAcrossRestart(t *testing.T) {
	s := storeTestService(t)
	mustCommand(t, s, "store-source-remove", "id", "test")
	s.loadStore()
	if len(s.store.Sources) != 0 {
		t.Fatal("removing all sources was undone on restart")
	}
}
func TestStoreGitHubContentUsesRawMediaType(t *testing.T) {
	request, _ := http.NewRequest("GET", "https://api.github.com/repos/example/apps/contents/catalog.json", nil)
	storeDownloadHeaders(request)
	if request.Header.Get("Accept") != "application/vnd.github.raw+json" {
		t.Fatal("GitHub would return JSON/base64 metadata instead of the signed bytes")
	}
}

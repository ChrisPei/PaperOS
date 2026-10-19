package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func waitLocation(t *testing.T, s *Service, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(4 * time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		okay := condition()
		s.mu.Unlock()
		if okay {
			return
		}
		time.Sleep(time.Millisecond * 5)
	}
	t.Fatal("weather operation did not finish")
}
func weatherFixture(w http.ResponseWriter, temp float64) {
	times := []int64{}
	values := []float64{}
	for i := 0; i < 72; i++ {
		times = append(times, 1760000400+int64(i)*3600)
		values = append(values, temp)
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"current": map[string]any{"temperature_2m": temp, "weather_code": 3},
		"daily":  map[string]any{"temperature_2m_max": []float64{temp + 2}, "temperature_2m_min": []float64{temp - 2}},
		"hourly": map[string]any{"time": times, "temperature_2m": values, "weather_code": values, "precipitation_probability": values, "wind_speed_10m": values}})
}
func TestWeatherLocationMigrationAndManualPersistence(t *testing.T) {
	s := testService(t)
	s.cfg.Weather = Weather{Fetched: 1234, Temperature: 17, Hours: []Hour{{Time: 1234}}}
	s.loadWeatherLocation()
	if s.cfg.WeatherLocation != defaultWeatherLocation() || s.cfg.Weather.Fetched != 1234 {
		t.Fatal("migration lost the default location's cache")
	}
	mustCommand(t, s, "weather-location-set", "name", "上海浦东", "latitude", "31.23", "longitude", "121.55")
	if s.cfg.Weather.Fetched != 0 || len(s.cfg.Weather.Hours) != 0 {
		t.Fatal("new place is displaying the old place's forecast")
	}
	data, e := os.ReadFile(filepath.Join(s.root, "state.json"))
	if e != nil {
		t.Fatal(e)
	}
	restarted := testService(t)
	if e = json.Unmarshal(data, &restarted.cfg); e != nil {
		t.Fatal(e)
	}
	restarted.loadWeatherLocation()
	if restarted.cfg.WeatherLocation.Name != "上海浦东" || restarted.cfg.WeatherLocation.Latitude != 31.23 {
		t.Fatal("saved place did not survive a new service instance")
	}
	mustCommand(t, s, "weather-location-default")
	if s.cfg.WeatherLocation != defaultWeatherLocation() {
		t.Fatal("default was not restored")
	}
}
func TestInvalidCoordinatesAndStaleResultsDoNotReplaceLocation(t *testing.T) {
	s := testService(t)
	s.loadWeatherLocation()
	original := s.cfg.WeatherLocation
	for _, pair := range [][2]string{{"NaN", "0"}, {"0", "Inf"}, {"91", "116"}, {"39", "181"}, {"hello", "116"}} {
		if e := s.command(url.Values{"cmd": {"weather-location-set"}, "name": {"测试"}, "latitude": {pair[0]}, "longitude": {pair[1]}}); e == nil {
			t.Fatal("invalid coordinates accepted", pair)
		}
		if s.cfg.WeatherLocation != original {
			t.Fatal("invalid input changed the selected place")
		}
	}
	if e := s.command(url.Values{"cmd": {"weather-location-select"}, "key": {"expired-0"}}); e == nil {
		t.Fatal("expired result accepted")
	}
}
func TestGeocodingParametersDisambiguationAndProviderFailure(t *testing.T) {
	s := testService(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		if q.Get("name") != "上海" || q.Get("language") != "zh" || q.Get("count") != "8" || q.Get("countryCode") != "CN" {
			t.Error("geocoding lost search parameters")
		}
		fmt.Fprint(w, `{"results":[{"id":1,"name":"上海","latitude":31.22,"longitude":121.46,"admin1":"上海市","admin2":"上海市","country":"中国"},{"id":2,"name":"上海","latitude":29.33,"longitude":121.06,"admin1":"浙江","admin2":"绍兴市","country":"中国"},{"id":3,"name":"missing coordinates"},{"id":1,"name":"duplicate","latitude":0,"longitude":0}]}`)
	}))
	defer server.Close()
	s.geocodingURL = server.URL
	places, e := s.fetchLocations(context.Background(), "上海")
	if e != nil || len(places) != 2 || places[0].Area != "中国 · 上海市" || !strings.Contains(places[1].Area, "浙江") {
		t.Fatal("same-name regions were not disambiguated", places, e)
	}
	server.Close()
	if _, e = s.fetchLocations(context.Background(), "上海"); e == nil {
		t.Fatal("provider failure was treated as valid results")
	}
}
func TestCitySuffixFallbackKeepsAdministrativeQualifier(t *testing.T) {
	s := testService(t)
	queries := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query().Get("name")
		queries = append(queries, query)
		if query == "杭州市,浙江" {
			fmt.Fprint(w, `{"results":[]}`)
			return
		}
		fmt.Fprint(w, `{"results":[{"id":1,"name":"杭州","latitude":30.27,"longitude":120.15,"admin1":"浙江","country":"中国"}]}`)
	}))
	defer server.Close()
	s.geocodingURL = server.URL
	places, e := s.fetchLocations(context.Background(), "杭州市,浙江")
	if e != nil || len(places) != 1 || strings.Join(queries, "|") != "杭州市,浙江|杭州,浙江" {
		t.Fatal("city suffix fallback lost the qualifier", queries, places, e)
	}
}
func TestExactCityOutranksUnrelatedLongerPrefix(t *testing.T) {
	s := testService(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("name") == "上海市" {
			fmt.Fprint(w, `{"results":[{"id":2,"name":"上海市场社区","latitude":34.66,"longitude":112.42,"country_code":"CN","admin1":"河南"}]}`)
			return
		}
		fmt.Fprint(w, `{"results":[{"id":1,"name":"上海","latitude":31.22,"longitude":121.46,"country_code":"CN","admin1":"上海市"}]}`)
	}))
	defer server.Close()
	s.geocodingURL = server.URL
	places, e := s.fetchLocations(context.Background(), "上海市")
	if e != nil || len(places) != 2 || places[0].Name != "上海" || places[0].Longitude != 121.46 {
		t.Fatal("unrelated prefix outranked the city", places, e)
	}
}
func TestNewSearchDiscardsOlderResponseAndOldSelectionKeys(t *testing.T) {
	s := testService(t)
	s.net.Connected = true
	oldStarted := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		name := r.URL.Query().Get("name")
		if name == "杭州" {
			close(oldStarted)
			<-release
		}
		fmt.Fprintf(w, `{"results":[{"id":1,"name":%q,"latitude":31.22,"longitude":121.46,"country":"中国"}]}`, name)
	}))
	defer server.Close()
	s.geocodingURL = server.URL
	mustCommand(t, s, "weather-search", "query", "杭州")
	<-oldStarted
	mustCommand(t, s, "weather-search", "query", "上海")
	waitLocation(t, s, func() bool { return !s.locationSearch.Busy && len(s.locationSearch.Places) == 1 })
	close(release)
	s.mu.Lock()
	place := s.locationSearch.Places[0]
	query := s.locationSearch.Query
	s.mu.Unlock()
	if query != "上海" || place.Name != "上海" {
		t.Fatal("older search overwrote the latest results")
	}
	if e := s.command(url.Values{"cmd": {"weather-location-select"}, "key": {"1-0"}}); e == nil {
		t.Fatal("previous search key was accepted")
	}
	mustCommand(t, s, "weather-location-select", "key", place.Key)
	waitLocation(t, s, func() bool { return !s.weatherBusy })
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cfg.WeatherLocation.Name != "上海" {
		t.Fatal("selection did not use provider coordinates")
	}
}
func TestPreviousWeatherRequestCannotOverwriteNewRegion(t *testing.T) {
	s := testService(t)
	s.loadWeatherLocation()
	s.net.Connected = true
	oldStarted := make(chan struct{})
	release := make(chan struct{})
	finished := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("latitude") == "39.9219" {
			close(oldStarted)
			<-release
			weatherFixture(w, 11)
		} else {
			weatherFixture(w, 29)
		}
	}))
	defer server.Close()
	s.weatherURL = server.URL
	go func() { s.refreshWeather(true); close(finished) }()
	<-oldStarted
	mustCommand(t, s, "weather-location-set", "name", "南京", "latitude", "32.06", "longitude", "118.78")
	waitLocation(t, s, func() bool { return s.cfg.Weather.Fetched > 0 && !s.weatherBusy })
	close(release)
	<-finished
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cfg.WeatherLocation.Name != "南京" || s.cfg.Weather.Temperature != 29 || s.weatherBusy {
		t.Fatal("old-region request replaced the new forecast")
	}
}

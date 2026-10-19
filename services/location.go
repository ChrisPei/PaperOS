package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type WeatherLocation struct {
	Name, Area          string
	Latitude, Longitude float64
}
type WeatherPlace struct {
	Key string
	WeatherLocation
}
type LocationSearch struct {
	Query, Message string
	Busy           bool
	Places         []WeatherPlace
}

func defaultWeatherLocation() WeatherLocation {
	return WeatherLocation{Name: "北京市朝阳区", Area: "北京 · 中国", Latitude: 39.9219, Longitude: 116.4436}
}
func validWeatherLocation(p WeatherLocation) bool {
	return strings.TrimSpace(p.Name) != "" && !math.IsNaN(p.Latitude) && !math.IsInf(p.Latitude, 0) &&
		!math.IsNaN(p.Longitude) && !math.IsInf(p.Longitude, 0) && math.Abs(p.Latitude) <= 90 && math.Abs(p.Longitude) <= 180
}
func (s *Service) weatherLocationLocked() WeatherLocation {
	if validWeatherLocation(s.cfg.WeatherLocation) {
		return s.cfg.WeatherLocation
	}
	return defaultWeatherLocation()
}
func (s *Service) loadWeatherLocation() {
	if !validWeatherLocation(s.cfg.WeatherLocation) {
		s.cfg.WeatherLocation = defaultWeatherLocation()
	}
}
func (s *Service) publishWeatherLocationLocked(b *strings.Builder) {
	p := s.weatherLocationLocked()
	fmt.Fprintf(b, "weather-location\t%s\t%s\t%g\t%g\t%t\n", field(p.Name), field(p.Area), p.Latitude, p.Longitude, s.weatherBusy)
	fmt.Fprintf(b, "location-search\t%s\t%t\t%s\t%d\n", field(s.locationSearch.Query), s.locationSearch.Busy, field(s.locationSearch.Message), s.locationSearchRun)
	for _, p := range s.locationSearch.Places {
		fmt.Fprintf(b, "place\t%s\t%s\t%s\t%g\t%g\n", p.Key, field(p.Name), field(p.Area), p.Latitude, p.Longitude)
	}
}
func (s *Service) setWeatherLocationLocked(p WeatherLocation) error {
	p.Name = strings.TrimSpace(clean(strings.TrimSpace(p.Name), 40))
	p.Area = clean(p.Area, 80)
	if !validWeatherLocation(p) {
		return errors.New("请填写地区名称和有效的经纬度")
	}
	previousLocation, previousWeather := s.cfg.WeatherLocation, s.cfg.Weather
	changed := p != s.weatherLocationLocked()
	s.cfg.WeatherLocation = p
	if changed {
		s.cfg.Weather = Weather{Message: "地区已更新，联网后获取天气"}
	}
	if e := s.saveLocked(); e != nil {
		s.cfg.WeatherLocation = previousLocation
		s.cfg.Weather = previousWeather
		return e
	}
	if changed {
		if s.weatherCancel != nil {
			s.weatherCancel()
			s.weatherCancel = nil
		}
		s.weatherRun++
		s.weatherBusy = false
	}
	s.message = "已保存天气地区"
	go s.refreshWeather(true)
	return nil
}
func (s *Service) weatherLocationCommandLocked(v url.Values) (bool, error) {
	switch v.Get("cmd") {
	case "weather-location-default":
		return true, s.setWeatherLocationLocked(defaultWeatherLocation())
	case "weather-location-set":
		latitude, e1 := strconv.ParseFloat(strings.TrimSpace(v.Get("latitude")), 64)
		longitude, e2 := strconv.ParseFloat(strings.TrimSpace(v.Get("longitude")), 64)
		if e1 != nil || e2 != nil {
			return true, errors.New("经纬度请填写数字，例如 39.9219 和 116.4436")
		}
		return true, s.setWeatherLocationLocked(WeatherLocation{Name: v.Get("name"), Area: "手动设置", Latitude: latitude, Longitude: longitude})
	case "weather-location-select":
		for _, p := range s.locationSearch.Places {
			if p.Key == v.Get("key") {
				return true, s.setWeatherLocationLocked(p.WeatherLocation)
			}
		}
		return true, errors.New("搜索结果已更新，请重新选择地区")
	case "weather-search":
		query := strings.TrimSpace(strings.ReplaceAll(v.Get("query"), "，", ","))
		if !utf8.ValidString(query) || utf8.RuneCountInString(query) < 2 || utf8.RuneCountInString(query) > 64 || clean(query, 64) != query {
			return true, errors.New("请输入 2 至 64 个字的城市或区县名称")
		}
		if !s.net.Connected || s.cfg.Airplane {
			return true, errors.New("请先连接 Wi-Fi；也可用经纬度手动设置地区")
		}
		if s.locationSearchCancel != nil {
			s.locationSearchCancel()
		}
		ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
		s.locationSearchCancel = cancel
		s.locationSearchRun++
		s.locationSearch = LocationSearch{Query: query, Busy: true, Message: "正在搜索地区…"}
		go s.searchLocations(ctx, cancel, query, s.locationSearchRun)
		return true, nil
	}
	return false, nil
}
func (s *Service) fetchLocations(ctx context.Context, query string) ([]WeatherLocation, error) {
	return s.fetchLocationsQuery(ctx, query, true)
}
func (s *Service) fetchLocationsQuery(ctx context.Context, query string, allowSuffix bool) ([]WeatherLocation, error) {
	endpoint := s.geocodingURL
	if endpoint == "" {
		endpoint = "https://geocoding-api.open-meteo.com/v1/search"
	}
	values := url.Values{"name": {query}, "count": {"8"}, "language": {"zh"}, "format": {"json"}, "countryCode": {"CN"}}
	request, e := http.NewRequestWithContext(ctx, "GET", endpoint+"?"+values.Encode(), nil)
	if e != nil {
		return nil, e
	}
	request.Header.Set("User-Agent", "PaperOS/0.2 (personal e-ink weather)")
	response, e := s.httpClient.Do(request)
	if e != nil {
		return nil, e
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return nil, errors.New("geocoding provider returned non-success")
	}
	data, e := io.ReadAll(io.LimitReader(response.Body, 256*1024+1))
	if e != nil || len(data) > 256*1024 {
		return nil, errors.New("geocoding response too large")
	}
	var raw struct {
		Error   bool `json:"error"`
		Results []struct {
			ID          int64    `json:"id"`
			Name        string   `json:"name"`
			Latitude    *float64 `json:"latitude"`
			Longitude   *float64 `json:"longitude"`
			Country     string   `json:"country"`
			CountryCode string   `json:"country_code"`
			Admin1      string   `json:"admin1"`
			Admin2      string   `json:"admin2"`
			Admin3      string   `json:"admin3"`
		} `json:"results"`
	}
	if e = json.Unmarshal(data, &raw); e != nil {
		return nil, e
	}
	if raw.Error || len(raw.Results) > 100 {
		return nil, errors.New("invalid geocoding result")
	}
	places := []WeatherLocation{}
	seen := map[int64]bool{}
	for _, r := range raw.Results {
		if len(places) == 8 {
			break
		}
		if r.ID <= 0 || seen[r.ID] || r.Latitude == nil || r.Longitude == nil || (r.CountryCode != "" && r.CountryCode != "CN") {
			continue
		}
		p := WeatherLocation{Name: clean(strings.TrimSpace(r.Name), 40), Latitude: *r.Latitude, Longitude: *r.Longitude}
		if !validWeatherLocation(p) {
			continue
		}
		parts := []string{}
		used := map[string]bool{p.Name: true}
		for _, part := range []string{r.Country, r.Admin1, r.Admin2, r.Admin3} {
			part = clean(strings.TrimSpace(part), 40)
			if part != "" && !used[part] {
				parts = append(parts, part)
				used[part] = true
			}
		}
		p.Area = clean(strings.Join(parts, " · "), 80)
		places = append(places, p)
		seen[r.ID] = true
	}
	if allowSuffix {
		parts := strings.SplitN(query, ",", 2)
		term := strings.TrimSpace(parts[0])
		for _, suffix := range []string{"市", "区", "县"} {
			base := strings.TrimSuffix(term, suffix)
			if base != term && utf8.RuneCountInString(base) >= 2 {
				baseQuery := base
				if len(parts) == 2 {
					baseQuery += "," + parts[1]
				}
				shorter, e := s.fetchLocationsQuery(ctx, baseQuery, false)
				if e != nil {
					if len(places) == 0 {
						return nil, e
					}
					break
				}
				combined := append(shorter, places...)
				score := func(p WeatherLocation) int {
					if p.Name == term {
						return 0
					}
					if p.Name == base {
						return 1
					}
					return 2
				}
				sort.SliceStable(combined, func(i, j int) bool { return score(combined[i]) < score(combined[j]) })
				places = nil
				dedup := map[WeatherLocation]bool{}
				for _, p := range combined {
					if !dedup[p] {
						places = append(places, p)
						dedup[p] = true
					}
					if len(places) == 8 {
						break
					}
				}
				break
			}
		}
	}
	return places, nil
}
func (s *Service) searchLocations(ctx context.Context, cancel context.CancelFunc, query string, generation uint64) {
	defer cancel()
	places, e := s.fetchLocations(ctx, query)
	s.mu.Lock()
	if generation != s.locationSearchRun {
		s.mu.Unlock()
		return
	}
	s.locationSearch.Busy = false
	s.locationSearchCancel = nil
	switch {
	case e != nil:
		s.locationSearch.Message = "搜索失败，请检查网络后重试"
	case len(places) == 0:
		s.locationSearch.Message = "未找到地区；可去掉市/区再试，或手动设置"
	default:
		s.locationSearch.Message = "点选地区保存，请核对所属省市"
		for i, p := range places {
			s.locationSearch.Places = append(s.locationSearch.Places, WeatherPlace{Key: fmt.Sprintf("%d-%d", generation, i), WeatherLocation: p})
		}
	}
	s.mu.Unlock()
	s.publish()
}

package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

type Hour struct {
	Time        int64
	Temperature float64
	Code        int
	Rain, Wind  float64
}
type Weather struct {
	Fetched     int64
	Temperature float64
	Code        int
	High, Low   float64
	Hours       []Hour
	Message     string
}

func (s *Service) fetchWeather() (Weather, error) {
	s.mu.Lock()
	location := s.weatherLocationLocked()
	s.mu.Unlock()
	return s.fetchWeatherAt(context.Background(), location)
}
func (s *Service) fetchWeatherAt(ctx context.Context, location WeatherLocation) (Weather, error) {
	query := url.Values{
		"latitude": {strconv.FormatFloat(location.Latitude, 'f', -1, 64)}, "longitude": {strconv.FormatFloat(location.Longitude, 'f', -1, 64)},
		"current":  {"temperature_2m,weather_code"},
		"hourly":   {"temperature_2m,precipitation_probability,weather_code,wind_speed_10m"},
		"daily":    {"temperature_2m_max,temperature_2m_min"},
		"timezone": {"Asia/Shanghai"}, "timeformat": {"unixtime"}, "forecast_days": {"3"},
	}
	request, e := http.NewRequestWithContext(ctx, "GET", s.weatherURL+"?"+query.Encode(), nil)
	if e != nil {
		return Weather{}, e
	}
	request.Header.Set("User-Agent", "PaperOS/0.2 (personal e-ink weather)")
	response, e := s.httpClient.Do(request)
	if e != nil {
		return Weather{}, e
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return Weather{}, errors.New("weather provider returned non-success")
	}
	data, e := io.ReadAll(io.LimitReader(response.Body, 256*1024+1))
	if e != nil || len(data) > 256*1024 {
		return Weather{}, errors.New("weather response too large")
	}
	var raw map[string]json.RawMessage
	if e = json.Unmarshal(data, &raw); e != nil {
		return Weather{}, e
	}
	var current map[string]json.RawMessage
	var daily map[string][]*float64
	var hourly map[string]json.RawMessage
	if json.Unmarshal(raw["current"], &current) != nil || json.Unmarshal(raw["daily"], &daily) != nil || json.Unmarshal(raw["hourly"], &hourly) != nil {
		return Weather{}, errors.New("invalid weather sections")
	}
	var temperature *float64
	var code *int
	_ = json.Unmarshal(current["temperature_2m"], &temperature)
	_ = json.Unmarshal(current["weather_code"], &code)
	hi, lo := daily["temperature_2m_max"], daily["temperature_2m_min"]
	if temperature == nil || code == nil || len(hi) == 0 || len(lo) == 0 || hi[0] == nil || lo[0] == nil {
		return Weather{}, errors.New("missing current or daily weather")
	}
	var times []int64
	var temps, probs, winds, codes []*float64
	_ = json.Unmarshal(hourly["time"], &times)
	_ = json.Unmarshal(hourly["temperature_2m"], &temps)
	_ = json.Unmarshal(hourly["precipitation_probability"], &probs)
	_ = json.Unmarshal(hourly["wind_speed_10m"], &winds)
	_ = json.Unmarshal(hourly["weather_code"], &codes)
	n := len(times)
	if n < 24 || n > 96 || len(temps) != n || len(probs) != n || len(winds) != n || len(codes) != n {
		return Weather{}, errors.New("invalid hourly forecast length")
	}
	w := Weather{Fetched: time.Now().Unix(), Temperature: *temperature, Code: *code, High: *hi[0], Low: *lo[0], Message: "Open-Meteo"}
	for i, stamp := range times {
		if temps[i] == nil || probs[i] == nil || winds[i] == nil || codes[i] == nil {
			continue
		}
		if i > 0 && stamp != times[i-1]+3600 {
			return Weather{}, errors.New("non-hourly weather timeline")
		}
		if *probs[i] < 0 || *probs[i] > 100 || *temps[i] < -100 || *temps[i] > 70 {
			return Weather{}, errors.New("weather values out of range")
		}
		w.Hours = append(w.Hours, Hour{stamp, *temps[i], int(*codes[i]), *probs[i], *winds[i]})
	}
	if len(w.Hours) < 24 {
		return Weather{}, errors.New("incomplete hourly weather")
	}
	return w, nil
}
func (s *Service) refreshWeather(force ...bool) {
	s.mu.Lock()
	forced := len(force) > 0 && force[0]
	if s.sleep.Busy || s.weatherBusy || !s.net.Connected || s.cfg.Airplane || (!forced && time.Now().Unix()-s.cfg.Weather.Fetched < 1800) {
		s.mu.Unlock()
		return
	}
	s.weatherBusy = true
	s.weatherRun++
	run := s.weatherRun
	location := s.weatherLocationLocked()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	s.weatherCancel = cancel
	s.mu.Unlock()
	defer cancel()
	s.publish()
	w, e := s.fetchWeatherAt(ctx, location)
	s.mu.Lock()
	defer func() { s.mu.Unlock(); s.publish() }()
	if run != s.weatherRun || location != s.weatherLocationLocked() {
		return // An older region must never overwrite the newly selected region.
	}
	s.weatherBusy = false
	s.weatherCancel = nil
	if e != nil {
		if s.cfg.Weather.Fetched > 0 {
			s.cfg.Weather.Message = "离线缓存 · 更新失败"
		} else {
			s.cfg.Weather.Message = "天气更新失败，请联网后重试"
		}
		return
	}
	s.cfg.Weather = w
	if e = s.saveLocked(); e != nil {
		s.cfg.Weather.Message = "天气缓存保存失败"
	}
}

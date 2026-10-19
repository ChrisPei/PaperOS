#ifndef PAPEROS_SERVICES_H
#define PAPEROS_SERVICES_H
#include <stdbool.h>
#include <stddef.h>
typedef struct { int id,hour,minute,days; bool enabled; char label[160]; long next; } PaperOSAlarm;
typedef struct { char ssid[160],hex[68],security[40]; int level; bool saved,current,available; } PaperOSWiFi;
typedef struct { long time; double temperature,rain,wind; int code; } PaperOSHour;
typedef struct { char key[32],name[160],area[256]; double latitude,longitude; } PaperOSPlace;
typedef struct {
    char id[65],path[768],title[256],credit[384];
    bool cached,favorite,fixed;
} PaperOSWallpaper;
typedef struct {
    PaperOSWallpaper photos[72]; int count;
    unsigned long revision; bool available;
} PaperOSGallery;
typedef struct { long at;int percent;bool powered,connected; } PaperOSBatteryPoint;
typedef struct { char date[16];int drop,wakes,end_percent;double observed,sleeping; } PaperOSBatteryDay;
typedef struct {
    bool available;unsigned long revision;long from,to;
    int drop,rtc,power,other,failures;double sleeping,observed;
    PaperOSBatteryDay days[7];int day_count;
    PaperOSBatteryPoint points[146];int point_count;
} PaperOSBatteryHistory;
typedef struct {
    char kind[24],label[160],room[128],value[160],unit[40],entity[160];
    bool available,stale;long at;
} PaperOSHomeItem;
typedef struct { PaperOSHomeItem items[12];int count;bool available;unsigned long revision; } PaperOSHome;
typedef struct {
    bool available,wifi,airplane,connected,busy,receiving;
    bool tailnet_installed,tailnet_enabled,tailnet_receive,tailnet_connected,tailnet_busy,tailnet_ready;
    char tailnet_name[96],tailnet_ip[64],tailnet_version[64],tailnet_message[256];
    char ip[64],ssid[160],net_message[256],message[256];
    bool time_auto,time_busy; long time_synced;
    char time_source[96],time_message[256];
    bool locked,wallpaper_busy; int idle_seconds,wallpaper_count; unsigned long lock_generation;
    bool power_known,external_power; int powered_multiplier,effective_idle_seconds;
    char wallpaper_path[768],wallpaper_title[256],wallpaper_credit[384],wallpaper_message[384];
    char wallpaper_mode[24],wallpaper_current[65],wallpaper_fixed[65],wallpaper_catalog[768];
    int wallpaper_favorites; unsigned long wallpaper_revision;
    PaperOSAlarm alarms[8]; int alarm_count;
    char timer_state[24]; int duration,remaining;
    char alert_id[128],alert_kind[24],alert_label[160]; int alert_duration;
    PaperOSWiFi networks[24]; int network_count;
    PaperOSWiFi saved_networks[32]; int saved_network_count;
    long weather_fetched; double temperature,high,low; int weather_code;
    char weather_message[160]; PaperOSHour hours[96]; int hour_count;
    char weather_name[160],weather_area[256]; double weather_latitude,weather_longitude; bool weather_busy;
    char location_query[256],location_message[256]; bool location_busy; unsigned long location_revision;
    PaperOSPlace places[8]; int place_count;
    bool sleep_enabled,sleep_available,sleep_usb_keep,sleep_usb;
    char sleep_phase[32],sleep_message[256],sleep_wake[40];
    long sleep_next,sleep_last;double sleep_seconds;unsigned long sleep_cycle;
    bool battery_available,battery_powered;int battery_percent;long battery_at;
    char battery_status[40],battery_history[768],battery_message[160];unsigned long battery_revision;
    bool home_configured,home_busy;long home_at;unsigned long home_revision;
    char home_name[160],home_catalog[768],home_message[256];
    bool store_busy; int store_progress; unsigned long store_revision;
    char store_phase[32],store_catalog[768],store_message[384],store_job[64],store_key[96],store_digest[65];
    char transfer_id[64],transfer_name[160],transfer_version[64],transfer_peer[80],transfer_code[16],transfer_digest[68];
} PaperOSServices;
bool paperos_services_read(PaperOSServices *state);
bool paperos_gallery_read(PaperOSGallery *gallery,const char *path,unsigned long revision);
bool paperos_battery_read(PaperOSBatteryHistory *history,const char *path,unsigned long revision);
bool paperos_home_read(PaperOSHome *home,const char *path,unsigned long revision);
bool paperos_service_command(const char *command,const char *const *arguments,char *message,size_t capacity);
#endif

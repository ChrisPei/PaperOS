#ifndef PAPEROS_DASHBOARD_H
#define PAPEROS_DASHBOARD_H
#include "services.h"
typedef struct { int x,y,w,h,kind,page; } PaperOSWidgetRect;
typedef struct {
    PaperOSServices services;
    PaperOSGallery gallery;
    PaperOSBatteryHistory battery;
    int battery_tab;
    PaperOSHome home;
    int home_tab,home_page;
    int wallpaper_page;bool wallpaper_favorites;
    char wallpaper_selected[65];
    int order[4], visible, widget_page, widget_pages;
    PaperOSWidgetRect widgets[4]; int widget_count;
    int alarm_tab,alarm_page,edit_id,edit_hour,edit_minute,edit_days;
    char edit_label[160]; bool delete_alarm;
    int duration,calendar_year,calendar_month,calendar_day,weather_page,network_page;
    int weather_location_page;
    bool network_saved,network_forget_confirm;
    PaperOSWiFi network_selected;
    char weather_query[256],weather_edit_name[128],weather_edit_latitude[40],weather_edit_longitude[40];
    int time_year,time_month,time_day,time_hour,time_minute,input_task,selected_network;
    long time_synced;
    bool adding_widget,preview,allow_commands,full_refresh,display_transition;
    long last_activity;
    long alert_started,flash_phase;
    char alert_seen[128],message[256];
    int return_screen;
} PaperOSDashboard;
#endif

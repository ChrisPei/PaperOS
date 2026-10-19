#define _POSIX_C_SOURCE 200809L
#include "services.h"
#include "store.h"
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>
static void put(char *to,size_t n,const char *from) { if(!strcmp(from,"-")) from=""; snprintf(to,n,"%s",from); }
static int split(char *line,char **parts,int size) {
    int n=0; char *p=line;
    while(p && n<size) { parts[n++]=p; p=strchr(p,'\t'); if(p) *p++=0; }
    return n;
}
bool paperos_services_read(PaperOSServices *state) {
    const char *path=getenv("PAPEROS_SERVICE_STATE"); if(!path) path="/run/paperos/state.tsv";
    FILE *f=fopen(path,"r"); if(!f) return false;
    char line[2048]; PaperOSServices s={0};
    if(!fgets(line,sizeof(line),f) || strcmp(line,"paperos-services-v1\n")) { fclose(f); return false; }
    int lines=0;
    while(fgets(line,sizeof(line),f) && ++lines<240) {
        size_t len=strlen(line); if(!len || line[len-1]!='\n') { fclose(f); return false; } line[len-1]=0;
        char *v[12]; int n=split(line,v,12);
        if(n==8 && !strcmp(v[0],"net")) {
            s.wifi=!strcmp(v[1],"true"); s.airplane=!strcmp(v[2],"true"); s.connected=!strcmp(v[3],"true");
            put(s.ip,sizeof(s.ip),v[4]); put(s.ssid,sizeof(s.ssid),v[5]); s.busy=!strcmp(v[6],"true"); put(s.net_message,sizeof(s.net_message),v[7]);
        } else if(n==8 && !strcmp(v[0],"alarm") && s.alarm_count<8) {
            PaperOSAlarm *a=&s.alarms[s.alarm_count++]; a->id=atoi(v[1]); a->hour=atoi(v[2]); a->minute=atoi(v[3]); a->days=atoi(v[4]); a->enabled=!strcmp(v[5],"true"); put(a->label,sizeof(a->label),v[6]); a->next=atol(v[7]);
        } else if(n==4 && !strcmp(v[0],"timer")) { put(s.timer_state,sizeof(s.timer_state),v[1]); s.duration=atoi(v[2]); s.remaining=atoi(v[3]); }
        else if(n==5 && !strcmp(v[0],"alert")) { put(s.alert_id,sizeof(s.alert_id),v[1]); put(s.alert_kind,sizeof(s.alert_kind),v[2]); put(s.alert_label,sizeof(s.alert_label),v[3]); s.alert_duration=atoi(v[4]); }
        else if(n==6 && !strcmp(v[0],"wifi") && s.network_count<24) { PaperOSWiFi *w=&s.networks[s.network_count++]; w->level=atoi(v[2]); put(w->security,sizeof(w->security),v[3]); put(w->ssid,sizeof(w->ssid),v[4]); put(w->hex,sizeof(w->hex),v[5]); }
        else if(n==7 && !strcmp(v[0],"wifi-saved") && s.saved_network_count<32) { PaperOSWiFi *w=&s.saved_networks[s.saved_network_count++]; put(w->ssid,sizeof(w->ssid),v[2]);put(w->hex,sizeof(w->hex),v[3]);w->saved=true;w->current=!strcmp(v[4],"true");w->available=!strcmp(v[5],"true");w->level=atoi(v[6]); }
        else if(n==7 && !strcmp(v[0],"weather")) { s.weather_fetched=atol(v[1]); s.temperature=atof(v[2]); s.weather_code=atoi(v[3]); s.high=atof(v[4]); s.low=atof(v[5]); put(s.weather_message,sizeof(s.weather_message),v[6]); }
        else if(n==6 && !strcmp(v[0],"weather-location")) {
            put(s.weather_name,sizeof(s.weather_name),v[1]);put(s.weather_area,sizeof(s.weather_area),v[2]);
            s.weather_latitude=atof(v[3]);s.weather_longitude=atof(v[4]);s.weather_busy=!strcmp(v[5],"true");
        }
        else if(n==5 && !strcmp(v[0],"location-search")) {
            put(s.location_query,sizeof(s.location_query),v[1]);s.location_busy=!strcmp(v[2],"true");
            put(s.location_message,sizeof(s.location_message),v[3]);s.location_revision=strtoul(v[4],NULL,10);
        }
        else if(n==6 && !strcmp(v[0],"place") && s.place_count<8) {
            PaperOSPlace *p=&s.places[s.place_count++];put(p->key,sizeof(p->key),v[1]);put(p->name,sizeof(p->name),v[2]);
            put(p->area,sizeof(p->area),v[3]);p->latitude=atof(v[4]);p->longitude=atof(v[5]);
        }
        else if(n==6 && !strcmp(v[0],"hour") && s.hour_count<96) { PaperOSHour *h=&s.hours[s.hour_count++]; h->time=atol(v[1]); h->temperature=atof(v[2]); h->code=atoi(v[3]); h->rain=atof(v[4]); h->wind=atof(v[5]); }
        else if(n==3 && !strcmp(v[0],"receive")) s.receiving=!strcmp(v[1],"true");
        else if(n==11 && !strcmp(v[0],"tailnet")) {
            s.tailnet_installed=!strcmp(v[1],"true");s.tailnet_enabled=!strcmp(v[2],"true");
            s.tailnet_receive=!strcmp(v[3],"true");s.tailnet_connected=!strcmp(v[4],"true");s.tailnet_busy=!strcmp(v[5],"true");
            put(s.tailnet_name,sizeof(s.tailnet_name),v[6]);put(s.tailnet_ip,sizeof(s.tailnet_ip),v[7]);
            put(s.tailnet_version,sizeof(s.tailnet_version),v[8]);put(s.tailnet_message,sizeof(s.tailnet_message),v[9]);
            s.tailnet_ready=!strcmp(v[10],"true");
        }
        else if(n==6 && !strcmp(v[0],"clock")) {
            s.time_auto=!strcmp(v[1],"true"); s.time_busy=!strcmp(v[2],"true"); s.time_synced=atol(v[3]);
            put(s.time_source,sizeof(s.time_source),v[4]); put(s.time_message,sizeof(s.time_message),v[5]);
        }
        else if(n==4 && !strcmp(v[0],"lock")) {
            s.locked=!strcmp(v[1],"true"); s.idle_seconds=atoi(v[2]); s.lock_generation=strtoul(v[3],NULL,10);
        }
        else if(n==5 && !strcmp(v[0],"power")) {
            s.power_known=!strcmp(v[1],"true");s.external_power=!strcmp(v[2],"true");
            s.powered_multiplier=atoi(v[3]);s.effective_idle_seconds=atoi(v[4]);
        }
        else if(n==7 && !strcmp(v[0],"wallpaper")) {
            put(s.wallpaper_path,sizeof(s.wallpaper_path),v[1]); put(s.wallpaper_title,sizeof(s.wallpaper_title),v[2]);
            put(s.wallpaper_credit,sizeof(s.wallpaper_credit),v[3]); s.wallpaper_count=atoi(v[4]);
            s.wallpaper_busy=!strcmp(v[5],"true"); put(s.wallpaper_message,sizeof(s.wallpaper_message),v[6]);
        }
        else if(n==7 && !strcmp(v[0],"gallery")) {
            put(s.wallpaper_mode,sizeof(s.wallpaper_mode),v[1]);s.wallpaper_favorites=atoi(v[2]);
            put(s.wallpaper_current,sizeof(s.wallpaper_current),v[3]);put(s.wallpaper_fixed,sizeof(s.wallpaper_fixed),v[4]);
            put(s.wallpaper_catalog,sizeof(s.wallpaper_catalog),v[5]);s.wallpaper_revision=strtoul(v[6],NULL,10);
        }
        else if(n==12 && !strcmp(v[0],"sleep")) {
            s.sleep_enabled=!strcmp(v[1],"true");s.sleep_available=!strcmp(v[2],"true");
            put(s.sleep_phase,sizeof(s.sleep_phase),v[3]);put(s.sleep_message,sizeof(s.sleep_message),v[4]);
            s.sleep_next=atol(v[5]);s.sleep_last=atol(v[6]);s.sleep_seconds=atof(v[7]);put(s.sleep_wake,sizeof(s.sleep_wake),v[8]);
            s.sleep_cycle=strtoul(v[9],NULL,10);s.sleep_usb_keep=!strcmp(v[10],"true");s.sleep_usb=!strcmp(v[11],"true");
        }
        else if(n==9 && !strcmp(v[0],"battery")) {
            s.battery_available=!strcmp(v[1],"true");s.battery_percent=atoi(v[2]);put(s.battery_status,sizeof(s.battery_status),v[3]);
            s.battery_powered=!strcmp(v[4],"true");s.battery_at=atol(v[5]);put(s.battery_history,sizeof(s.battery_history),v[6]);
            s.battery_revision=strtoul(v[7],NULL,10);put(s.battery_message,sizeof(s.battery_message),v[8]);
        }
        else if(n==8&&!strcmp(v[0],"mihome")){
            s.home_configured=!strcmp(v[1],"true");s.home_busy=!strcmp(v[2],"true");s.home_at=atol(v[3]);
            put(s.home_name,sizeof(s.home_name),v[4]);put(s.home_catalog,sizeof(s.home_catalog),v[5]);s.home_revision=strtoul(v[6],NULL,10);put(s.home_message,sizeof(s.home_message),v[7]);
        }
        else if(n==10 && !strcmp(v[0],"store")) {
            s.store_busy=!strcmp(v[1],"true");put(s.store_phase,sizeof(s.store_phase),v[2]);s.store_progress=atoi(v[3]);s.store_revision=strtoul(v[4],NULL,10);
            put(s.store_catalog,sizeof(s.store_catalog),v[5]);put(s.store_message,sizeof(s.store_message),v[6]);put(s.store_job,sizeof(s.store_job),v[7]);put(s.store_key,sizeof(s.store_key),v[8]);put(s.store_digest,sizeof(s.store_digest),v[9]);
        }
        else if(n==7 && !strcmp(v[0],"transfer")) {
            put(s.transfer_id,sizeof(s.transfer_id),v[1]); put(s.transfer_name,sizeof(s.transfer_name),v[2]); put(s.transfer_version,sizeof(s.transfer_version),v[3]); put(s.transfer_peer,sizeof(s.transfer_peer),v[4]); put(s.transfer_code,sizeof(s.transfer_code),v[5]); put(s.transfer_digest,sizeof(s.transfer_digest),v[6]);
        } else if(n==2 && !strcmp(v[0],"message")) put(s.message,sizeof(s.message),v[1]);
    }
    bool okay=!ferror(f) && lines<240; fclose(f); if(!okay) return false;
    for(int i=0;i<s.network_count;i++)for(int j=0;j<s.saved_network_count;j++)if(!strcmp(s.networks[i].hex,s.saved_networks[j].hex)){s.networks[i].saved=true;s.networks[i].current=s.saved_networks[j].current;}
    s.available=true; *state=s; return true;
}
bool paperos_gallery_read(PaperOSGallery *gallery,const char *path,unsigned long revision) {
    FILE *f=fopen(path,"r");if(!f)return false;
    char line[2048];unsigned long actual=0;PaperOSGallery next={0};
    if(!fgets(line,sizeof(line),f)||sscanf(line,"paperos-wallpapers-v1\t%lu",&actual)!=1||actual!=revision){fclose(f);return false;}
    while(fgets(line,sizeof(line),f)){
        size_t length=strlen(line);if(!length||line[length-1]!='\n'||next.count>=72){fclose(f);return false;}line[length-1]=0;
        char *v[10];int n=split(line,v,10);
        if(n!=8||strcmp(v[0],"photo")||strlen(v[1])!=64){fclose(f);return false;}
        for(int i=0;i<64;i++)if(!((v[1][i]>='0'&&v[1][i]<='9')||(v[1][i]>='a'&&v[1][i]<='f'))){fclose(f);return false;}
        PaperOSWallpaper *p=&next.photos[next.count++];
        put(p->id,sizeof(p->id),v[1]);put(p->path,sizeof(p->path),v[2]);put(p->title,sizeof(p->title),v[3]);put(p->credit,sizeof(p->credit),v[4]);
        p->cached=!strcmp(v[5],"true");p->favorite=!strcmp(v[6],"true");p->fixed=!strcmp(v[7],"true");
    }
    bool okay=!ferror(f);fclose(f);if(!okay)return false;
    next.revision=revision;next.available=true;*gallery=next;return true;
}
bool paperos_battery_read(PaperOSBatteryHistory *history,const char *path,unsigned long revision) {
    FILE *f=fopen(path,"r");if(!f)return false;
    char line[512];unsigned long actual=0;PaperOSBatteryHistory next={0};
    if(!fgets(line,sizeof(line),f)||sscanf(line,"paperos-battery-v1\t%lu",&actual)!=1||actual!=revision){fclose(f);return false;}
    int lines=0;
    while(fgets(line,sizeof(line),f)&&++lines<160){
        size_t len=strlen(line);if(!len||line[len-1]!='\n'){fclose(f);return false;}line[len-1]=0;
        char *v[12];int n=split(line,v,12);
        if(n==10&&!strcmp(v[0],"summary")){
            next.from=atol(v[1]);next.to=atol(v[2]);next.drop=atoi(v[3]);next.sleeping=atof(v[4]);next.observed=atof(v[5]);
            next.rtc=atoi(v[6]);next.power=atoi(v[7]);next.other=atoi(v[8]);next.failures=atoi(v[9]);
            if(!isfinite(next.sleeping)||!isfinite(next.observed)||next.sleeping<0||next.observed<0){fclose(f);return false;}
        }else if(n==7&&!strcmp(v[0],"day")&&next.day_count<7){
            PaperOSBatteryDay *d=&next.days[next.day_count++];put(d->date,sizeof(d->date),v[1]);d->drop=atoi(v[2]);d->observed=atof(v[3]);d->sleeping=atof(v[4]);d->wakes=atoi(v[5]);d->end_percent=atoi(v[6]);
            if(!isfinite(d->observed)||!isfinite(d->sleeping)){fclose(f);return false;}
        }else if(n==5&&!strcmp(v[0],"point")&&next.point_count<146){
            PaperOSBatteryPoint *p=&next.points[next.point_count++];p->at=atol(v[1]);p->percent=atoi(v[2]);p->powered=!strcmp(v[3],"true");p->connected=!strcmp(v[4],"true");
            if(p->percent<0||p->percent>100){fclose(f);return false;}
        }else{fclose(f);return false;}
    }
    bool okay=!ferror(f)&&lines<160;fclose(f);if(!okay)return false;
    next.revision=revision;next.available=true;*history=next;return true;
}
bool paperos_home_read(PaperOSHome *home,const char *path,unsigned long revision){
    FILE *f=fopen(path,"r");if(!f)return false;char line[1536];unsigned long actual=0;PaperOSHome next={0};
    if(!fgets(line,sizeof(line),f)||sscanf(line,"paperos-mihome-v1\t%lu",&actual)!=1||actual!=revision){fclose(f);return false;}
    while(fgets(line,sizeof(line),f)){
        size_t len=strlen(line);if(!len||line[len-1]!='\n'||next.count>=12){fclose(f);return false;}line[len-1]=0;
        char *v[12];int n=split(line,v,12);if(n!=10||strcmp(v[0],"item")){fclose(f);return false;}
        PaperOSHomeItem *item=&next.items[next.count++];put(item->kind,sizeof(item->kind),v[1]);put(item->label,sizeof(item->label),v[2]);put(item->room,sizeof(item->room),v[3]);
        put(item->value,sizeof(item->value),v[4]);put(item->unit,sizeof(item->unit),v[5]);item->available=!strcmp(v[6],"true");item->stale=!strcmp(v[7],"true");item->at=atol(v[8]);put(item->entity,sizeof(item->entity),v[9]);
    }
    bool okay=!ferror(f);fclose(f);if(!okay)return false;next.available=true;next.revision=revision;*home=next;return true;
}
bool paperos_store_read(PaperOSStoreCatalog *catalog,const char *path,unsigned long revision) {
    FILE *f=fopen(path,"r");if(!f)return false;
    PaperOSStoreCatalog *next=calloc(1,sizeof(*next));if(!next){fclose(f);return false;}
    char line[4096];unsigned long actual=0;bool okay=false;
    if(!fgets(line,sizeof(line),f)||sscanf(line,"paperos-store-v1\t%lu",&actual)!=1||actual!=revision)goto end;
    int lines=0;
    while(fgets(line,sizeof(line),f)){
        size_t len=strlen(line);if(!len||line[len-1]!='\n'||++lines>PAPEROS_STORE_MAX+17)goto end;line[len-1]=0;
        char *v[20];int n=split(line,v,20);
        if(n==2&&!strcmp(v[0],"sort")){if(!strcmp(v[1],"recent"))next->sort_mode=1;else if(!strcmp(v[1],"name"))next->sort_mode=2;}
        else if(n==7&&((!strcmp(v[0],"source")&&next->source_count<8)||(!strcmp(v[0],"preset")&&next->preset_count<8))){
            PaperOSStoreSource *p=!strcmp(v[0],"source")?&next->sources[next->source_count++]:&next->presets[next->preset_count++];
            put(p->id,sizeof(p->id),v[1]);put(p->name,sizeof(p->name),v[2]);put(p->url,sizeof(p->url),v[3]);put(p->format,sizeof(p->format),v[4]);p->enabled=!strcmp(v[5],"true");put(p->error,sizeof(p->error),v[6]);
        }else if((n==14||n==18)&&!strcmp(v[0],"app")&&next->count<PAPEROS_STORE_MAX){
            PaperOSStoreEntry *p=&next->entries[next->count++];
            put(p->key,sizeof(p->key),v[1]);put(p->id,sizeof(p->id),v[2]);put(p->name,sizeof(p->name),v[3]);put(p->version,sizeof(p->version),v[4]);put(p->installed,sizeof(p->installed),v[5]);put(p->kind,sizeof(p->kind),v[6]);put(p->source,sizeof(p->source),v[7]);put(p->size,sizeof(p->size),v[8]);put(p->reason,sizeof(p->reason),v[9]);put(p->description,sizeof(p->description),v[10]);p->update=!strcmp(v[11],"true");put(p->url,sizeof(p->url),v[12]);put(p->sha256,sizeof(p->sha256),v[13]);
            const char *separator=strchr(p->key,':');if(separator){size_t length=(size_t)(separator-p->key);if(length>=sizeof(p->source_id))goto end;memcpy(p->source_id,p->key,length);p->source_id[length]=0;}
            p->stars=-1;
            if(n==18){char *end;long stars=strtol(v[14],&end,10);if(end!=v[14]&&!*end&&stars>=0&&stars<=1000000000)p->stars=stars;put(p->updated,sizeof(p->updated),v[15]);put(p->category,sizeof(p->category),v[16]);put(p->stats_source,sizeof(p->stats_source),v[17]);}
        }else goto end;
    }
    okay=!ferror(f);if(okay){next->revision=revision;next->available=true;*catalog=*next;}
end:
    free(next);fclose(f);return okay;
}
static bool encode(char *buffer,size_t size,size_t *used,const char *value) {
    for(const unsigned char *p=(const unsigned char*)value;*p;p++) {
        bool simple=(*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||*p=='-'||*p=='_'||*p=='.';
        size_t needed=simple?1:3; if(*used+needed>=size) return false;
        if(simple) buffer[(*used)++]=(char)*p; else { static const char hex[]="0123456789ABCDEF"; buffer[(*used)++]='%'; buffer[(*used)++]=hex[*p>>4]; buffer[(*used)++]=hex[*p&15]; }
    }
    buffer[*used]=0; return true;
}
bool paperos_service_command(const char *command,const char *const *arguments,char *message,size_t capacity) {
    char body[8192]="cmd="; size_t used=4;
    if(!encode(body,sizeof(body),&used,command)) return false;
    for(int i=0;arguments && arguments[i] && arguments[i+1];i+=2) {
        if(used+2>=sizeof(body)) return false;
        body[used++]='&'; if(!encode(body,sizeof(body),&used,arguments[i])) return false;
        body[used++]='='; if(!encode(body,sizeof(body),&used,arguments[i+1])) return false;
    }
    const char *path=getenv("PAPEROS_SERVICE_SOCKET"); if(!path) path="/run/paperos/services.sock";
    struct sockaddr_un address={.sun_family=AF_UNIX};
    if(strlen(path)>=sizeof(address.sun_path)) return false;
    memcpy(address.sun_path,path,strlen(path)+1);
    int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0); if(fd<0) return false;
    struct timeval timeout={2,0}; setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)); setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    if(connect(fd,(struct sockaddr*)&address,sizeof(address))) { close(fd); snprintf(message,capacity,"后台服务未连接"); return false; }
    char request[9000]; int length=snprintf(request,sizeof(request),"POST /command HTTP/1.0\r\nHost: paperos\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: %zu\r\n\r\n%s",used,body);
    if(length<0 || (size_t)length>=sizeof(request)) { close(fd); return false; }
    size_t sent=0; while(sent<(size_t)length) { ssize_t n=send(fd,request+sent,(size_t)length-sent,MSG_NOSIGNAL); if(n<=0) { close(fd); snprintf(message,capacity,"服务请求失败"); return false; } sent+=(size_t)n; }
    memset(request,0,sizeof(request)); memset(body,0,sizeof(body));
    char response[4096]={0}; used=0; ssize_t n;
    while(used<sizeof(response)-1 && (n=read(fd,response+used,sizeof(response)-1-used))>0) used+=(size_t)n;
    close(fd); response[used]=0;
    int status=0; sscanf(response,"HTTP/%*s %d",&status);
    if(status==200) { if(capacity) message[0]=0; return true; }
    char *detail=strstr(response,"\r\n\r\n"); if(detail) { detail+=4; detail[strcspn(detail,"\r\n")]=0; }
    snprintf(message,capacity,"%s",detail?detail:"后台操作失败"); return false;
}

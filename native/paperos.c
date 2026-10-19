#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/fb.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/time.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "apps.h"
#include "ime.h"
#include "input.h"
#include "keyboard.h"
#include "calendar.h"
#include "dashboard.h"
#include "muyu.h"
#include "store.h"
#ifdef PAPEROS_NDS
#include "nds/player.h"
#endif
#ifdef HAVE_FBINK
#include <fbink.h>
#endif
#define STB_TRUETYPE_IMPLEMENTATION
#define STBTT_STATIC
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#include "stb_truetype.h"
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

#define W 600
#define H 800
#define MAX_AGENTS 48
#define MAX_BODY 65536
#define MAX_NOTE 2048

typedef enum { HOME, AGENTS, CLOCK, NOTES, SYSTEM, APP_LIBRARY, APP_DETAILS, INPUT_METHOD,
    SETTINGS, WIDGETS, ALARM, ALARM_EDIT, TIME_SET, CALENDAR, WEATHER, MIHOME, NETWORK, LOCK_SETTINGS,
    WALLPAPERS, WALLPAPER_PREVIEW, WALLPAPER_FULLSCREEN, WEATHER_LOCATION, WEATHER_COORDINATES, POWER_SETTINGS, BATTERY, TAILNET, MUYU, NETWORK_PROFILE, STORE_DETAILS, STORE_SOURCES
#ifdef PAPEROS_NDS
    ,NDS_GAME
#endif
} Screen;
typedef struct { char id[96], source[24], name[256], state[32]; long updated; } Agent;
typedef struct {
    Screen screen;
    Agent agents[MAX_AGENTS];
    int count, page;
    bool connected, dirty, note_saved, input_requested;
    PaperOSKeyboard keyboard;
    char input_message[128];
    long snapshot;
    char note[MAX_NOTE], note_path[512];
    char url[512], token[256];
    PaperOSApp apps[PAPEROS_MAX_APPS], packages[PAPEROS_MAX_APPS];
    int app_count, package_count, app_page, home_page, selected_app, launch_app;
    bool show_packages, standalone, return_requested, confirm_remove, overlay_bridge, overlay_return;
    unsigned apps_installed, apps_removed, apps_launched, app_returns;
    char app_root[512], package_root[512], app_message[256];
    PaperOSDashboard ui;
    PaperOSMuyu muyu;
    PaperOSStoreUI store;
#ifdef PAPEROS_NDS
    PaperOSNDS nds;
#endif
} App;
static unsigned char pixels[W * H];
static stbtt_fontinfo font;
static unsigned char *font_bytes;
static volatile sig_atomic_t stopped;
static void on_signal(int sig) { (void)sig; stopped = 1; }
static void copy_text(char *dest, size_t n, const char *src) {
    if (!n) return;
    size_t len = strlen(src);
    if (len >= n) {
        len = n - 1;
        while (len && (((unsigned char)src[len] & 0xc0) == 0x80)) len--;
    }
    memcpy(dest, src, len); dest[len] = '\0';
}
static unsigned char *read_file(const char *path, size_t limit, size_t *length) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    unsigned char *b = calloc(limit + 1, 1);
    if (!b) { fclose(f); return NULL; }
    size_t n = fread(b, 1, limit, f);
    if (ferror(f) || fgetc(f) != EOF) { free(b); fclose(f); return NULL; }
    fclose(f); if (length) *length = n; return b;
}
static int codepoint(const char **text) {
    const unsigned char *p = (const unsigned char *)*text;
    if (!*p) return 0;
    int result = *p++, count = 0;
    if (result >= 0xf0 && result <= 0xf4) { result &= 7; count = 3; }
    else if (result >= 0xe0 && result < 0xf0) { result &= 15; count = 2; }
    else if (result >= 0xc2 && result < 0xe0) { result &= 31; count = 1; }
    else if (result >= 0x80) result = '?';
    for (int i = 0; i < count; i++) {
        if (!*p || (*p & 0xc0) != 0x80) { result = '?'; break; }
        result = (result << 6) | (*p++ & 63);
    }
    *text = (const char *)p; return result;
}
static void rect(int x, int y, int w, int h, unsigned char value) {
    int x0 = x < 0 ? 0 : x, y0 = y < 0 ? 0 : y;
    int x1 = x + w > W ? W : x + w, y1 = y + h > H ? H : y + h;
    for (int row = y0; row < y1; row++) if (x1 > x0) memset(pixels + row * W + x0, value, (size_t)(x1 - x0));
}
static void box(int x, int y, int w, int h, unsigned char value) {
    rect(x,y,w,2,value); rect(x,y+h-2,w,2,value); rect(x,y,2,h,value); rect(x+w-2,y,2,h,value);
}
static int text_width(const char *str, int size) {
    float scale = stbtt_ScaleForPixelHeight(&font, (float)size);
    int width = 0, advance, bearing;
    const char *p = str;
    while (*p) { int cp = codepoint(&p); stbtt_GetCodepointHMetrics(&font, cp, &advance, &bearing); width += (int)(advance * scale + 0.5f); }
    return width;
}
static int text(int x, int y, int size, const char *str, int max_width, unsigned char color) {
    float scale = stbtt_ScaleForPixelHeight(&font, (float)size);
    int ascent, descent, gap; stbtt_GetFontVMetrics(&font, &ascent, &descent, &gap);
    int baseline = y + (int)(ascent * scale + 0.5f), start = x;
    const char *p = str;
    while (*p) {
        int cp = codepoint(&p), advance, bearing, bw, bh, ox, oy;
        stbtt_GetCodepointHMetrics(&font, cp, &advance, &bearing);
        int step = (int)(advance * scale + 0.5f);
        if (max_width > 0 && x + step > start + max_width) break;
        unsigned char *bitmap = stbtt_GetCodepointBitmap(&font, scale, scale, cp, &bw, &bh, &ox, &oy);
        if (bitmap) {
            for (int by = 0; by < bh; by++) for (int bx = 0; bx < bw; bx++) {
                int px = x + ox + bx, py = baseline + oy + by;
                if (px >= 0 && px < W && py >= 0 && py < H) {
                    int a = bitmap[by*bw+bx];
                    pixels[py*W+px] = (unsigned char)((pixels[py*W+px]*(255-a) + color*a) / 255);
                }
            }
            stbtt_FreeBitmap(bitmap, NULL);
        }
        x += step;
    }
    return x - start;
}
static void centered(int y, int size, const char *str) { text((W-text_width(str,size))/2,y,size,str,W,0); }
static const char *state_label(const char *state) {
    if (!strcmp(state,"running")) return "运行中";
    if (!strcmp(state,"waiting")) return "等你处理";
    if (!strcmp(state,"completed")) return "已完成";
    if (!strcmp(state,"failed")) return "失败";
    if (!strcmp(state,"idle")) return "空闲";
    if (!strcmp(state,"stopped")) return "已停止";
    return "状态未知";
}
static int counts(App *a, const char *state) {
    int n=0; for (int i=0;i<a->count;i++) if (!strcmp(a->agents[i].state,state)) n++; return n;
}
static void dash_status(App *a);
static void header(App *a,const char *title, const char *subtitle) {
    dash_status(a);
    text(30,56,40,title,540,0); text(30,106,20,subtitle,540,65);
    rect(30,143,540,2,0);
}
static void button(int x,int y,int w,int h,const char *label,bool dark) {
    rect(x,y,w,h,dark?0:255); box(x,y,w,h,0);
    int size=28; while(size>18 && text_width(label,size)>w-14)size--;
    text(x+(w-text_width(label,size))/2,y+(h-size)/2,size,label,w-12,dark?255:0);
}
static void store_input(App *a,int task);
static void store_library(App *a);
#include "dashboard.inc"
#include "muyu.inc"
static void footer(App *a) {
    if(a->standalone) { button(20,732,560,52,"返回主页",false); return; }
    rect(0,724,600,1,120);
    const char *labels[]={"主页","应用","设置"};
    for(int i=0;i<3;i++) {
        int center=100+i*200;
        int icon_extent=i==1?28:30; /* Include the two-pixel outline. */
        dash_icon(i,center-icon_extent/2,748-icon_extent/2,28);
        text(center-text_width(labels[i],25)/2,769,25,labels[i],110,0);
        bool active=i==0?a->screen==HOME:i==1?(a->screen==APP_LIBRARY || a->screen==APP_DETAILS || a->screen==STORE_DETAILS || a->screen==STORE_SOURCES):a->screen==SETTINGS;
        if(active) rect(center-48,795,96,3,0);
    }
}
static void draw_home(App *a) {
    dash_home(a);
}
static void draw_agents(App *a) {
    header(a,"Agent 状态","Cowork + Codex");
    char buf[160];
    snprintf(buf,sizeof(buf),"%d 运行   %d 等待   %d 完成",counts(a,"running"),counts(a,"waiting"),counts(a,"completed"));
    text(30,164,26,buf,540,0);
    int start=a->page*4;
    for(int row=0;row<4 && start+row<a->count;row++) {
        Agent *agent=&a->agents[start+row]; int y=212+row*105;
        if(!strcmp(agent->state,"waiting")) rect(30,y,5,91,0);
        text(45,y+4,17,agent->source,370,75);
        text(45,y+31,25,agent->name,490,0);
        text(45,y+64,19,state_label(agent->state),340,55);
        rect(30,y+99,540,1,185);
    }
    if(!a->count) { text(45,247,26,"还没有状态数据",500,0); text(45,292,20,"连接电脑端 PaperOS Bridge 后显示",510,80); }
    snprintf(buf,sizeof(buf),"%s  ·  第 %d / %d 页",a->connected?"已连接":"离线缓存",a->page+1,(a->count+3)/4? (a->count+3)/4:1);
    text(30,650,18,buf,540,60);
    if(a->snapshot>0) {
        time_t stamp=(time_t)a->snapshot; struct tm local; localtime_r(&stamp,&local);
        strftime(buf,sizeof(buf),"最近数据  %H:%M:%S",&local); text(30,677,17,buf,300,85);
    }
    if(a->count>4) { button(360,657,96,44,"上页",false); button(474,657,96,44,"下页",false); }
}
static void draw_clock(App *a) {
    header(a,a->standalone?"独立时钟":"时钟预览","按分钟更新");
    time_t now=time(NULL); struct tm local; localtime_r(&now,&local); char buf[96];
    strftime(buf,sizeof(buf),"%H:%M",&local); centered(275,155,buf);
    strftime(buf,sizeof(buf),"%Y 年 %m 月 %d 日",&local); centered(462,32,buf);
    centered(594,21,"慢一点，也可以看见进展。");
}
static void wrap_note(App *a) {
    const char *p=a->note; int y=196, x=47;
    while(*p && y<590) {
        const char *before=p; int cp=codepoint(&p); char glyph[8]={0};
        size_t n=(size_t)(p-before); if(n>=sizeof(glyph)) break; memcpy(glyph,before,n);
        if(cp=='\t') copy_text(glyph,sizeof(glyph),"    ");
        if(cp=='\n') { x=47; y+=30; continue; }
        int width=text_width(glyph,25);
        if(x+width>548) { x=47; y+=30; }
        text(x,y,25,glyph,510,0); x+=width;
    }
}
static void draw_notes(App *a) {
    header(a,"记事本",a->note_saved?"已保存到本机":"点击文字区域，打开系统输入法");
    box(30,174,540,426,170); wrap_note(a);
    if(!a->note[0]) text(47,196,24,"点这里输入笔记",500,125);
    button(30,620,261,60,"编辑文字",false); button(309,620,261,60,"保存",true);
    if(a->input_message[0]) text(30,692,17,a->input_message,540,70);
}
static void edit_note(App *a) {
    a->input_requested=false;
    int status=paperos_input_text("编辑笔记",a->note,PAPEROS_INPUT_MULTILINE,a->note,sizeof(a->note));
    if(status==PAPEROS_INPUT_ACCEPTED) { a->note_saved=false; copy_text(a->input_message,sizeof(a->input_message),"文字已更新，点保存写入本机"); }
    else if(status==PAPEROS_INPUT_CANCELLED) copy_text(a->input_message,sizeof(a->input_message),"已取消编辑，原文字保留");
    else if(status==PAPEROS_INPUT_BUSY) copy_text(a->input_message,sizeof(a->input_message),"系统输入法正在使用中，请稍后再试");
    else copy_text(a->input_message,sizeof(a->input_message),"系统输入法暂不可用，原文字保留");
    a->dirty=true;
}
static void draw_input_preview(PaperOSKeyboard *k) {
    char display[PAPEROS_INPUT_MAX+sizeof(k->preedit)+1];
    size_t pending=strlen(k->preedit), cursor=k->cursor+pending;
    memcpy(display,k->request.text,k->cursor);
    memcpy(display+k->cursor,k->preedit,pending);
    memcpy(display+cursor,k->request.text+k->cursor,strlen(k->request.text+k->cursor)+1);
    int line=0,x=24,cursor_line=0; size_t at=0;
    const char *p=display;
    while(*p) {
        const char *before=p; int cp=codepoint(&p); char glyph[8]={0};
        size_t n=(size_t)(p-before); memcpy(glyph,before,n);
        if(cp=='\t') copy_text(glyph,sizeof(glyph),"    ");
        if(k->request.flags&PAPEROS_INPUT_PASSWORD) copy_text(glyph,sizeof(glyph),"•");
        int width=cp=='\n'?0:text_width(glyph,25);
        if(x+width>576) { x=24; line++; }
        if(at==cursor) cursor_line=line;
        if(cp=='\n') { x=24; line++; } else x+=width;
        at+=n;
    }
    if(at==cursor) cursor_line=line;
    int first=cursor_line>13?cursor_line-13:0;
    x=24; line=0; at=0; p=display;
    while(*p) {
        const char *before=p; int cp=codepoint(&p); char glyph[8]={0};
        size_t n=(size_t)(p-before); memcpy(glyph,before,n);
        if(cp=='\t') copy_text(glyph,sizeof(glyph),"    ");
        if(k->request.flags&PAPEROS_INPUT_PASSWORD) copy_text(glyph,sizeof(glyph),"•");
        int width=cp=='\n'?0:text_width(glyph,25);
        if(x+width>576) { x=24; line++; }
        if(line>=first && line<first+14) {
            int y=86+(line-first)*30;
            if(at==cursor) rect(x,y,2,27,0);
            if(cp!='\n') text(x,y,25,glyph,552,0);
            if(at>=k->cursor && at<cursor) rect(x,y+27,width,1,0);
        }
        if(cp=='\n') { x=24; line++; } else x+=width;
        at+=n;
    }
    if(at==cursor && line>=first && line<first+14) rect(x,86+(line-first)*30,2,27,0);
    if(!display[0]) text(29,86,25,"输入文字…",540,150);
    memset(display,0,sizeof(display));
}
static void key_line(int x0,int y0,int x1,int y1,unsigned char color) {
    int dx=abs(x1-x0),sx=x0<x1?1:-1,dy=-abs(y1-y0),sy=y0<y1?1:-1,error=dx+dy;
    for(;;) {
        rect(x0,y0,2,2,color); if(x0==x1 && y0==y1) break;
        int twice=2*error; if(twice>=dy) { error+=dy; x0+=sx; } if(twice<=dx) { error+=dx; y0+=sy; }
    }
}
static void keyboard_button(int x,int y,int w,int h,const char *label,int control,bool dark,bool special) {
    unsigned char fill=dark?0:(special?232:255),ink=dark?255:0;
    if(control<0 || (control>=PAPEROS_KEY_SHIFT && control!=PAPEROS_KEY_MORE)) {
        rect(x+3,y,w-6,h,85); rect(x+1,y+1,w-2,h-2,85); rect(x,y+3,w,h-6,85);
        rect(x+3,y+1,w-6,h-4,fill); rect(x+1,y+3,w-2,h-6,fill);
    } else if(dark) { rect(x,y,w,h,0); }
    int cx=x+w/2,cy=y+h/2;
    if(control==PAPEROS_KEY_BACKSPACE) {
        key_line(cx-17,cy,cx-8,cy-10,ink); key_line(cx-8,cy-10,cx+16,cy-10,ink);
        key_line(cx+16,cy-10,cx+16,cy+10,ink); key_line(cx+16,cy+10,cx-8,cy+10,ink); key_line(cx-8,cy+10,cx-17,cy,ink);
        key_line(cx-1,cy-5,cx+8,cy+5,ink); key_line(cx-1,cy+5,cx+8,cy-5,ink); return;
    }
    if(control==PAPEROS_KEY_SHIFT && !strcmp(label,"⇧")) {
        key_line(cx,cy-13,cx-13,cy,ink); key_line(cx,cy-13,cx+13,cy,ink);
        key_line(cx-13,cy,cx-6,cy,ink); key_line(cx+13,cy,cx+6,cy,ink);
        key_line(cx-6,cy,cx-6,cy+11,ink); key_line(cx+6,cy,cx+6,cy+11,ink); key_line(cx-6,cy+11,cx+6,cy+11,ink); return;
    }
    if(control==PAPEROS_KEY_ENTER && !strcmp(label,"↵")) {
        key_line(cx+12,cy-9,cx+12,cy+4,ink); key_line(cx+12,cy+4,cx-11,cy+4,ink);
        key_line(cx-11,cy+4,cx-4,cy-3,ink); key_line(cx-11,cy+4,cx-4,cy+11,ink); return;
    }
    int size=control==PAPEROS_KEY_MORE?32:(control<0?27:20);
    text(x+(w-text_width(label,size))/2,y+(h-size)/2-1,size,label,w-4,ink);
}
static void draw_input_method(App *a) {
    PaperOSKeyboard *k=&a->keyboard;
    const char *title=k->request.title[0]?k->request.title:"输入文字";
    int title_width=text_width(title,22); if(title_width>256) title_width=256;
    text(160+(256-title_width)/2,21,22,title,256,0);
    rect(0,66,W,1,180); draw_input_preview(k);
    if(k->message[0]) text(24,507,16,k->message,552,45);
    rect(0,PAPEROS_KB_TOP,W,H-PAPEROS_KB_TOP,246); rect(0,PAPEROS_KB_TOP,W,1,100);
    rect(0,PAPEROS_KB_GRID_TOP-1,W,1,195);
    for(int i=0;i<5 && k->candidate_page*5+i<k->candidate_count;i++) {
        int x=19+i*98,index=k->candidate_page*5+i;
        text(x+6,534,22,k->candidates[index],86,0);
        if(i) rect(x,534,1,20,190);
    }
    if(!k->candidate_count) {
        const char *mode=k->alpha_mode==PAPEROS_KB_CHINESE?"拼音":(k->mode==PAPEROS_KB_UPPER?"英文 · 大写":"英文");
        if(k->request.flags&PAPEROS_INPUT_PASSWORD) mode="密码";
        else if(k->mode==PAPEROS_KB_NUMBERS) mode="数字";
        else if(k->mode==PAPEROS_KB_SYMBOLS) mode="符号";
        text(24,535,18,mode,480,90);
    }
    const char *keys=paperos_keyboard_keys(k);
    for(int i=0;i<26;i++) {
        int x,y,w,h; if(!paperos_keyboard_key(k,i,&x,&y,&w,&h)) break;
        char label[2]={keys[i],0}; keyboard_button(x,y,w,h,label,-1,false,false);
    }
    if(k->mode<=PAPEROS_KB_UPPER) keyboard_button(525,626,53,51,k->mode==PAPEROS_KB_CHINESE?"：":":",-1,false,false);
    for(int control=0;control<PAPEROS_KEY_COUNT;control++) {
        if(control==PAPEROS_KEY_MORE && k->candidate_count<=5) continue;
        int x,y,w,h; paperos_keyboard_control(control,&x,&y,&w,&h);
        bool dark=control==PAPEROS_KEY_DONE || (control==PAPEROS_KEY_SHIFT && k->mode==PAPEROS_KB_UPPER);
        bool special=control==PAPEROS_KEY_SHIFT || control==PAPEROS_KEY_BACKSPACE || control==PAPEROS_KEY_LAYOUT || control==PAPEROS_KEY_LANGUAGE || control==PAPEROS_KEY_ENTER;
        keyboard_button(x,y,w,h,paperos_keyboard_label(k,control),control,dark,special);
    }
}
static void draw_system(App *a) {
    header(a,"系统信息","独立用户空间 · 原生墨水屏界面");
    struct utsname u; char buf[256]; int y=185;
    if(!uname(&u)) { snprintf(buf,sizeof(buf),"%s  %s",u.sysname,u.release); text(30,y,25,buf,540,0); y+=45; text(30,y,23,u.machine,540,70); y+=55; }
    FILE *f=fopen("/proc/meminfo","r"); long total=0,available=-1,free_mem=0,buffers=0,cached=0,reclaim=0,shmem=0; char line[256];
    if(f) { while(fgets(line,sizeof(line),f)) {
        if(sscanf(line,"MemTotal: %ld",&total)==1) continue;
        if(sscanf(line,"MemAvailable: %ld",&available)==1) continue;
        if(sscanf(line,"MemFree: %ld",&free_mem)==1) continue;
        if(sscanf(line,"Buffers: %ld",&buffers)==1) continue;
        if(sscanf(line,"Cached: %ld",&cached)==1) continue;
        if(sscanf(line,"SReclaimable: %ld",&reclaim)==1) continue;
        if(sscanf(line,"Shmem: %ld",&shmem)==1) continue;
    } fclose(f); }
    bool estimated=available<0;
    if(estimated) { available=free_mem+buffers+cached+reclaim-shmem; if(available<0) available=0; if(available>total) available=total; }
    snprintf(buf,sizeof(buf),"内存  %ld MiB / %s %ld MiB",total/1024,estimated?"估算可用":"可用",available/1024); text(30,y,24,buf,540,0); y+=60;
    struct statvfs v; if(!statvfs("/",&v)) { snprintf(buf,sizeof(buf),"根文件系统可用  %llu MiB",(unsigned long long)v.f_bavail*v.f_frsize/1048576); text(30,y,24,buf,540,0); y+=60; }
    text(30,y,24,"显示  600 × 800 · 灰度",540,0); y+=60;
    bool charging;int capacity=dash_battery(&charging);
    if(capacity>=0){snprintf(buf,sizeof(buf),"电池  %d%% · %s",capacity,charging?"充电中":capacity==100?"已充满":"使用电池");text(30,y,24,buf,540,0);y+=60;}
    text(30,y,20,"设置  /etc/paperos.env",540,70); y+=38;
    text(30,y,20,"应用数据  /var/lib/paperos",540,70);
}
static void reload_apps(App *a) {
    a->app_count=paperos_apps_scan(a->app_root,true,a->apps,PAPEROS_MAX_APPS);
    a->package_count=paperos_apps_scan(a->package_root,false,a->packages,PAPEROS_MAX_APPS);
    int count=a->show_packages?a->package_count:a->app_count;
    if(a->app_page*4>=count) a->app_page=0;
    if(a->home_page*6>=a->app_count) a->home_page=0;
}
static void draw_library(App *a) {
    if(!a->show_packages){store_library(a);return;}
    header(a,"应用库","打开应用，退出后回到这里");
    button(30,166,261,48,"已安装",!a->show_packages); button(309,166,261,48,"接收的应用包",a->show_packages);
    PaperOSApp *items=a->show_packages?a->packages:a->apps;
    int count=a->show_packages?a->package_count:a->app_count;
    for(int row=0;row<4 && a->app_page*4+row<count;row++) {
        PaperOSApp *item=&items[a->app_page*4+row]; int y=235+row*91;
        box(30,y,540,80,175); text(47,y+9,27,item->name,490,0);
        text(47,y+46,18,item->version,100,70); text(160,y+46,18,item->description,380,70);
    }
    if(!count) {
        text(30,259,27,a->show_packages?"没有发现应用包":"还没有安装其他应用",540,0);
        text(30,305,21,"应用包放入 USB 的 paperos/packages",540,70);
    }
    if(a->app_message[0]) text(30,619,20,a->app_message,540,30);
    if(count>4) { button(30,659,110,43,"上页",false); button(158,659,110,43,"下页",false); }
    button(435,659,135,43,"刷新",false);
}
static void draw_app_details(App *a) {
    int count=a->show_packages?a->package_count:a->app_count;
    if(a->selected_app<0 || a->selected_app>=count) { a->screen=APP_LIBRARY; draw_library(a); return; }
    PaperOSApp *item=(a->show_packages?a->packages:a->apps)+a->selected_app;
    bool installed=!a->show_packages;
    for(int i=0;a->show_packages && i<a->app_count;i++) if(!strcmp(item->id,a->apps[i].id)) installed=true;
    header(a,item->name,item->version); text(30,183,24,item->description,540,0);
    text(30,238,20,installed?(a->show_packages?"已安装 · 可以更新":"已安装的应用"):"准备安装的应用",540,70);
    button(30,333,261,82,a->show_packages?(installed?"更新":"安装"):"打开",true);
    button(309,333,261,82,installed?(a->confirm_remove?"确认卸载":"卸载"):"返回列表",false);
    text(30,453,21,"关闭应用后，启动器会自动接管屏幕。",540,65);
    if(a->app_message[0]) text(30,527,22,a->app_message,540,0);
    button(30,650,540,48,"返回应用库",false);
}
#include "store.inc"
#ifdef PAPEROS_NDS
#include "nds/ui.inc"
#endif
static void draw(App *a) {
    memset(pixels,255,sizeof(pixels));
    if(a->ui.services.alert_id[0]) { dash_overlay(a); a->dirty=false; return; }
    if(a->ui.services.locked) {
        dash_lock(a);
        if(a->overlay_bridge)button(28,720,544,54,"返回 PaperOS",false);
        a->dirty=false; return;
    }
    if(a->ui.services.transfer_id[0]) { dash_overlay(a); a->dirty=false; return; }
    switch(a->screen) {
        case HOME: draw_home(a); break; case AGENTS: draw_agents(a); break;
        case CLOCK: draw_clock(a); break; case NOTES: draw_notes(a); break; case SYSTEM: draw_system(a); break;
        case APP_LIBRARY: draw_library(a); break; case APP_DETAILS: draw_app_details(a); break;
        case INPUT_METHOD: draw_input_method(a); break;
        case SETTINGS: dash_settings(a); break; case WIDGETS: dash_widgets(a); break;
        case ALARM: dash_alarm(a); break; case ALARM_EDIT: dash_alarm_edit(a); break;
        case TIME_SET: dash_time(a); break; case CALENDAR: dash_calendar(a); break;
        case WEATHER: dash_weather(a); break; case MIHOME: dash_mihome(a); break;
        case WEATHER_LOCATION: dash_weather_location(a); break;
        case WEATHER_COORDINATES: dash_weather_coordinates(a); break;
        case POWER_SETTINGS: dash_power(a); break;
        case BATTERY: dash_battery_page(a); break;
        case TAILNET: dash_tailnet(a); break;
        case MUYU: muyu_draw(a); break;
        case NETWORK_PROFILE: dash_network_profile(a); break;
        case STORE_DETAILS: store_details(a); break;
        case STORE_SOURCES: store_sources(a); break;
        case NETWORK: dash_network(a); break;
        case LOCK_SETTINGS: dash_lock_settings(a); break;
        case WALLPAPERS: dash_wallpapers(a); break;
        case WALLPAPER_PREVIEW: dash_wallpaper_preview(a); break;
        case WALLPAPER_FULLSCREEN: dash_wallpaper_fullscreen(a); break;
#ifdef PAPEROS_NDS
        case NDS_GAME: nds_draw(a); break;
#endif
    }
    if(a->screen!=INPUT_METHOD&&a->screen!=WALLPAPER_FULLSCREEN
#ifdef PAPEROS_NDS
       &&a->screen!=NDS_GAME
#endif
    ) footer(a);
    a->dirty=false;
}
static bool save_note(App *a) {
    char temp[sizeof(a->note_path)+16]; snprintf(temp,sizeof(temp),"%s.tmp.XXXXXX",a->note_path);
    int fd=mkstemp(temp); if(fd<0) return false;
    size_t len=strlen(a->note),pos=0;
    while(pos<len) { ssize_t n=write(fd,a->note+pos,len-pos); if(n<=0) { close(fd); unlink(temp); return false; } pos+=(size_t)n; }
    if(fsync(fd)!=0) { close(fd); unlink(temp); return false; }
    if(close(fd)!=0 || rename(temp,a->note_path)!=0) { unlink(temp); return false; }
    return true;
}
static void tap(App *a,int x,int y) {
    if(!a->ui.preview || a->ui.allow_commands) dash_tick(a);
    if(!a->ui.services.locked) dash_activity(a);
    if(a->ui.services.locked && !a->ui.services.alert_id[0]) {
        if(a->overlay_bridge&&x>=28&&x<572&&y>=720&&y<774){
            dash_command(a,"lock-unlock",NULL);a->overlay_return=true;a->return_requested=true;
        }
        return;
    }
    if(a->ui.services.alert_id[0] || a->ui.services.transfer_id[0]) { dash_tap(a,x,y); a->dirty=true; return; }
#ifdef PAPEROS_NDS
    if(a->screen==NDS_GAME){
        if(nds_obscured(a)){
            if(a->ui.services.alert_id[0]||a->ui.services.transfer_id[0])dash_tap(a,x,y);
            a->dirty=true;return;
        }
        nds_tap(a,x,y);return;
    }
#endif
    if(a->screen==WALLPAPER_FULLSCREEN){a->screen=WALLPAPER_PREVIEW;a->ui.display_transition=true;a->dirty=true;return;}
    if(a->screen==INPUT_METHOD) { paperos_keyboard_tap(&a->keyboard,x,y,getenv("PAPEROS_IME_HELPER")); a->dirty=true; return; }
    if(y<724 && dash_tap(a,x,y)) { a->dirty=true; return; }
    if(y<724 && store_tap(a,x,y)){a->dirty=true;return;}
    if(a->screen==MUYU&&y<724){muyu_hit(a,x,y);return;}
    if(y>=724 && y<800) {
        if(a->standalone) { a->return_requested=true; a->dirty=true; return; }
        if(x<200) { reload_apps(a); a->screen=HOME; }
        else if(x<400) { reload_apps(a); a->show_packages=false; a->screen=APP_LIBRARY; } else a->screen=SETTINGS;
    } else if(a->screen==HOME) {
        if(y>=244 && y<304) a->screen=x<300?AGENTS:SYSTEM;
        else if(y>=365 && y<637 && x>=30 && x<570) {
            int col=x<300?0:1,row=(y-365)/96,index=a->home_page*6+row*2+col;
            if((y-365)%96<80 && (x<291 || x>=309) && index<a->app_count) a->launch_app=index;
        } else if(y>=665 && y<707 && x>=30 && x<570) {
            if(a->app_count>6 && x<130 && a->home_page>0) a->home_page--;
            else if(a->app_count>6 && x>=470 && (a->home_page+1)*6<a->app_count) a->home_page++;
            else if(a->app_count<=6 || (x>=148 && x<452)) { reload_apps(a); a->show_packages=false; a->screen=APP_LIBRARY; }
        }
    } else if(a->screen==APP_LIBRARY) {
        if(y>=166 && y<214) { a->show_packages=x>=300; a->app_page=0; a->app_message[0]=0; reload_apps(a); }
        else if(y>=235 && y<599) {
            int row=(y-235)/91,count=a->show_packages?a->package_count:a->app_count;
            if((y-235)%91<80 && a->app_page*4+row<count) { a->selected_app=a->app_page*4+row; a->confirm_remove=false; a->app_message[0]=0; a->screen=APP_DETAILS; }
        } else if(y>=659 && y<702) {
            int count=a->show_packages?a->package_count:a->app_count;
            if(x>=30 && x<140 && a->app_page>0) a->app_page--;
            else if(x>=158 && x<268 && (a->app_page+1)*4<count) a->app_page++;
            else if(x>=435) reload_apps(a);
        }
    } else if(a->screen==APP_DETAILS) {
        if(y>=650 && y<698) { a->screen=APP_LIBRARY; a->confirm_remove=false; }
        else if(y>=333 && y<415 && a->selected_app>=0) {
            if(x>=30 && x<291) {
                if(a->show_packages && a->selected_app<a->package_count) {
                    if(!paperos_app_install(a->app_root,a->packages[a->selected_app].directory,a->app_message,sizeof(a->app_message))) {
                        a->apps_installed++; a->show_packages=false; reload_apps(a); a->screen=APP_LIBRARY;
                    }
                } else if(!a->show_packages && a->selected_app<a->app_count) a->launch_app=a->selected_app;
            } else if(x>=309 && x<570) {
                int count=a->show_packages?a->package_count:a->app_count;
                if(a->selected_app<count) {
                    PaperOSApp *item=(a->show_packages?a->packages:a->apps)+a->selected_app;
                    bool installed=!a->show_packages;
                    for(int i=0;a->show_packages && i<a->app_count;i++) if(!strcmp(item->id,a->apps[i].id)) installed=true;
                    if(!installed) { a->screen=APP_LIBRARY; a->dirty=true; return; }
                    if(!a->confirm_remove) a->confirm_remove=true;
                    else if(!paperos_app_remove(a->app_root,item->id,a->app_message,sizeof(a->app_message))) { a->apps_removed++; reload_apps(a); a->screen=APP_LIBRARY; a->confirm_remove=false; }
                }
            }
        }
    } else if(a->screen==AGENTS && y>=657 && y<701) {
        if(x>=360 && x<456 && a->page>0) a->page--;
        if(x>=474 && x<570 && (a->page+1)*4<a->count) a->page++;
    } else if(a->screen==NOTES) {
        if(x>=30 && x<570 && y>=174 && y<600) a->input_requested=true;
        else if(y>=620 && y<680) {
            if(x>=30 && x<291) a->input_requested=true;
            else if(x>=309 && x<570) {
                a->note_saved=save_note(a);
                copy_text(a->input_message,sizeof(a->input_message),a->note_saved?"已保存":"保存失败，文字仍在，请稍后重试");
            }
        }
    }
    a->dirty=true;
}
static bool parse_feed(App *a,char *body) {
    long stamp=0; int expected=0, consumed=0;
    char *save=NULL,*line=strtok_r(body,"\n",&save);
    if(!line || sscanf(line,"paperos-v1\t%ld\t%d%n",&stamp,&expected,&consumed)!=2 ||
       !consumed || line[consumed] || stamp<0 || expected<0 || expected>MAX_AGENTS) return false;
    Agent parsed[MAX_AGENTS]; memset(parsed,0,sizeof(parsed)); int count=0;
    while((line=strtok_r(NULL,"\n",&save))) {
        if(count>=MAX_AGENTS) return false;
        char *columns[5],*p=line; columns[0]=p;
        for(int col=1;col<5;col++) { p=strchr(p,'\t'); if(!p) return false; *p++=0; columns[col]=p; }
        if(strchr(columns[4],'\t')) return false;
        for(int col=0;col<5;col++) if(!columns[col][0]) return false;
        const char *state=columns[3];
        if(strcmp(state,"running") && strcmp(state,"waiting") && strcmp(state,"completed") &&
           strcmp(state,"failed") && strcmp(state,"idle") && strcmp(state,"stopped") && strcmp(state,"unknown")) return false;
        copy_text(parsed[count].id,sizeof(parsed[count].id),columns[0]);
        copy_text(parsed[count].source,sizeof(parsed[count].source),columns[1]);
        copy_text(parsed[count].name,sizeof(parsed[count].name),columns[2]);
        copy_text(parsed[count].state,sizeof(parsed[count].state),columns[3]);
        char *end; errno=0; parsed[count].updated=strtol(columns[4],&end,10);
        if(errno || *end || parsed[count].updated<0) return false;
        count++;
    }
    if(count!=expected) return false;
    bool changed=count!=a->count || memcmp(parsed,a->agents,sizeof(parsed))!=0 || !a->connected;
    memcpy(a->agents,parsed,sizeof(parsed)); a->count=count; a->snapshot=stamp; a->connected=true;
    if(a->page*4>=a->count) a->page=0;
    if(changed) a->dirty=true;
    return true;
}
static bool fetch_feed(App *a) {
    if(strncmp(a->url,"http://",7)) return false;
    char url[sizeof(a->url)]; copy_text(url,sizeof(url),a->url+7);
    char *path=strchr(url,'/'); char request_path[512]="/v1/agents.tsv";
    if(path) { copy_text(request_path,sizeof(request_path),path); *path=0; }
    char *port=strchr(url,':'); if(port) *port++=0; else port="8086";
    if(strchr(url,'@') || strchr(request_path,'\r') || strchr(request_path,'\n')) return false;
    char *port_end; long number=strtol(port,&port_end,10);
    if(*port_end || number<1 || number>65535) return false;
    struct sockaddr_in address={0}; address.sin_family=AF_INET; address.sin_port=htons((uint16_t)number);
    if(inet_pton(AF_INET,url,&address.sin_addr)!=1) return false;
    int fd=socket(AF_INET,SOCK_STREAM,0); if(fd<0) return false;
    fcntl(fd,F_SETFL,O_NONBLOCK);
    int status=connect(fd,(struct sockaddr*)&address,sizeof(address));
    if(status<0 && errno==EINPROGRESS) {
        struct pollfd poller={fd,POLLOUT,0}; int error=1; socklen_t error_length=sizeof(error);
        if(poll(&poller,1,2000)>0 && getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&error_length)==0 && error==0) status=0;
    }
    if(status!=0) { close(fd); return false; }
    fcntl(fd,F_SETFL,0);
    struct timeval timeout={2,0}; setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)); setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    char request[1600],auth[300]="";
    if(a->token[0] && !strchr(a->token,'\r') && !strchr(a->token,'\n')) snprintf(auth,sizeof(auth),"Authorization: Bearer %s\r\n",a->token);
    int len=snprintf(request,sizeof(request),"GET %s HTTP/1.0\r\nHost: %s\r\n%sConnection: close\r\n\r\n",request_path,url,auth);
    size_t sent=0;
    while(sent<(size_t)len) { ssize_t n=send(fd,request+sent,(size_t)len-sent,0); if(n<=0) { close(fd); return false; } sent+=(size_t)n; }
    char *response=calloc(MAX_BODY+4097,1); if(!response) { close(fd); return false; }
    size_t used=0; bool ok=true;
    while(used<MAX_BODY+4096) { ssize_t n=recv(fd,response+used,MAX_BODY+4096-used,0); if(n==0) break; if(n<0) { ok=false; break; } used+=(size_t)n; }
    close(fd); if(used>=MAX_BODY+4096) ok=false;
    int http_status=0; sscanf(response,"HTTP/%*s %d",&http_status); char *body=strstr(response,"\r\n\r\n");
    ok=ok && http_status==200 && body && parse_feed(a,body+4); free(response); return ok;
}
#ifdef HAVE_FBINK
static void touch_position(int fd,bool mt,const struct input_absinfo *ax,const struct input_absinfo *ay,int *x,int *y) {
    *x=ax->value; *y=ay->value;
    if(fd<0 || !mt) return;
    struct input_absinfo slot;
    if(ioctl(fd,EVIOCGABS(ABS_MT_SLOT),&slot) || slot.value<0 || slot.value>=32) return;
    int values[33]={0}; values[0]=ABS_MT_POSITION_X;
    if(!ioctl(fd,EVIOCGMTSLOTS(sizeof(values)),values)) *x=values[slot.value+1];
    values[0]=ABS_MT_POSITION_Y;
    if(!ioctl(fd,EVIOCGMTSLOTS(sizeof(values)),values)) *y=values[slot.value+1];
}
static int touch_open(const char *requested,struct input_absinfo *ax,struct input_absinfo *ay,bool *mt) {
    for(int i=0;i<32;i++) {
        char path[128]; if(requested && *requested) copy_text(path,sizeof(path),requested); else snprintf(path,sizeof(path),"/dev/input/event%d",i);
        int fd=open(path,O_RDONLY|O_NONBLOCK); if(fd<0) { if(requested) break; continue; }
        if(ioctl(fd,EVIOCGABS(ABS_MT_POSITION_X),ax)==0 && ioctl(fd,EVIOCGABS(ABS_MT_POSITION_Y),ay)==0) *mt=true;
        else if(ioctl(fd,EVIOCGABS(ABS_X),ax)==0 && ioctl(fd,EVIOCGABS(ABS_Y),ay)==0) *mt=false;
        else { close(fd); if(requested) break; continue; }
        if(ax->maximum>ax->minimum && ay->maximum>ay->minimum) {
            if(ioctl(fd,EVIOCGRAB,1)<0) perror("Touch device grab");
            return fd;
        }
        close(fd); if(requested) break;
    }
    return -1;
}
static int display_solid_phase(int fb,unsigned char shade,const FBInkConfig *config) {
    static unsigned char solid[W*H];memset(solid,shade,sizeof(solid));
    int result=fbink_print_raw_data(fb,solid,W,H,sizeof(solid),0,0,config);
    return result<0?result:fbink_wait_for_complete(fb,LAST_MARKER);
}
static void record_lock_refresh(int black,int white,int image) {
    bool complete=black>=0&&white>=0&&image>=0;
    char temporary[]="/run/paperos/lock-refresh.XXXXXX";int fd=mkstemp(temporary);
    if(fd>=0){
        char record[192];int size=snprintf(record,sizeof(record),"%s\tBLACK_WHITE_IMAGE_GC16_FULL\t%d\t%d\t%d\t%ld\n",complete?"complete":"failed",black,white,image,(long)time(NULL));
        bool okay=write(fd,record,(size_t)size)==size;
        if(close(fd))okay=false;
        if(okay)okay=rename(temporary,"/run/paperos/lock-refresh.state")==0;
        if(!okay)unlink(temporary);
    }
    if(!complete)fprintf(stderr,"Lock screen full cleanup failed: black=%d white=%d image=%d\n",black,white,image);
}
static void record_sleep_ready(App *a) {
    PaperOSServices *s=&a->ui.services;
    if(!s->locked||s->alert_id[0]||strcmp(s->sleep_phase,"preparing"))return;
    char temporary[]="/run/paperos/sleep-display.XXXXXX";int fd=mkstemp(temporary);
    if(fd<0)return;
    char record[160];int size=snprintf(record,sizeof(record),"ready\t%lu\t%lu\t%ld\t%ld\n",s->sleep_cycle,s->lock_generation,dash_mono(),(long)getpid());
    bool okay=write(fd,record,(size_t)size)==size;if(close(fd))okay=false;
    if(okay)okay=rename(temporary,"/run/paperos/sleep-display.state")==0;
    if(!okay)unlink(temporary);
}
#endif
static Screen parse_screen(const char *str) {
    if(!strcmp(str,"keyboard")) return INPUT_METHOD;
    if(!strcmp(str,"agents")) return AGENTS;
    if(!strcmp(str,"clock")) return CLOCK;
    if(!strcmp(str,"notes")) return NOTES;
    if(!strcmp(str,"system")) return SYSTEM;
    if(!strcmp(str,"apps")) return APP_LIBRARY;
    if(!strcmp(str,"settings")) return SETTINGS;
    if(!strcmp(str,"widgets")) return WIDGETS;
    if(!strcmp(str,"alarm")) return ALARM;
    if(!strcmp(str,"timer")) return ALARM;
    if(!strcmp(str,"calendar")) return CALENDAR;
    if(!strcmp(str,"weather")) return WEATHER;
    if(!strcmp(str,"weather-location")) return WEATHER_LOCATION;
    if(!strcmp(str,"weather-coordinates")) return WEATHER_COORDINATES;
    if(!strcmp(str,"power-settings")) return POWER_SETTINGS;
    if(!strcmp(str,"battery")) return BATTERY;
    if(!strcmp(str,"tailscale")) return TAILNET;
    if(!strcmp(str,"muyu")) return MUYU;
    if(!strcmp(str,"wifi-profile")) return NETWORK_PROFILE;
    if(!strcmp(str,"mihome")) return MIHOME;
    if(!strcmp(str,"lock-settings")) return LOCK_SETTINGS;
    if(!strcmp(str,"wallpapers")) return WALLPAPERS;
    if(!strcmp(str,"wallpaper-preview")) return WALLPAPER_PREVIEW;
    if(!strcmp(str,"wallpaper-fullscreen")) return WALLPAPER_FULLSCREEN;
    if(!strcmp(str,"network")) return NETWORK;
    return HOME;
}
static int wait_application(pid_t child) {
    int status=0; pid_t result;
    while((result=waitpid(child,&status,WNOHANG))==0 && !stopped) poll(NULL,0,100);
    if(!result && stopped) {
        kill(-child,SIGTERM);
        for(int attempt=0;attempt<20 && (result=waitpid(child,&status,WNOHANG))==0;attempt++) poll(NULL,0,100);
        if(!result) { kill(-child,SIGKILL); do { result=waitpid(child,&status,0); } while(result<0 && errno==EINTR); }
    }
    if(result<0) return 126;
    return WIFEXITED(status)?WEXITSTATUS(status):(WIFSIGNALED(status)?128+WTERMSIG(status):126);
}
static bool finish_input(App *app,int fd,bool okay) {
    PaperOSInputReply reply={.status=PAPEROS_INPUT_CANCELLED};
    if(!okay) reply.status=PAPEROS_INPUT_FAILED;
    else if(!stopped && app->keyboard.status==PAPEROS_INPUT_ACCEPTED) {
        reply.status=PAPEROS_INPUT_ACCEPTED;
        memcpy(reply.text,app->keyboard.request.text,strlen(app->keyboard.request.text)+1);
    }
    paperos_keyboard_close(&app->keyboard);
    bool sent=fd<0 || paperos_input_write_reply(fd,&reply,2000);
    if(fd>=0) close(fd);
    memset(&reply,0,sizeof(reply)); return sent;
}
int main(int argc,char **argv) {
    signal(SIGPIPE,SIG_IGN);
    App app={0}; app.dirty=true; app.launch_app=-1; app.keyboard.engine.input=app.keyboard.engine.output=-1;
    const char *program_name=strrchr(argv[0],'/');program_name=program_name?program_name+1:argv[0];
    if(!strcmp(program_name,"paperos-muyu")){app.screen=MUYU;app.standalone=true;}
    const char *install=NULL,*remove_id=NULL,*run_id=NULL; bool list_apps=false,system_overlay_only=false;
    const char *font_path=getenv("PAPEROS_FONT"),*render=NULL,*feed=NULL,*report=NULL;
    unsigned run_seconds=0;
    int input_fd=-1;
    PaperOSInputRequest input_request={.flags=PAPEROS_INPUT_MULTILINE,.max_bytes=PAPEROS_INPUT_MAX,.title="输入文字"};
    if(!font_path) font_path="/usr/share/paperos/NotoSansCJKsc-Regular.otf";
    const char *env=getenv("PAPEROS_BRIDGE_URL"); if(env) copy_text(app.url,sizeof(app.url),env);
    env=getenv("PAPEROS_BRIDGE_TOKEN"); if(env) copy_text(app.token,sizeof(app.token),env);
    env=getenv("PAPEROS_NOTE"); copy_text(app.note_path,sizeof(app.note_path),env?env:"/var/lib/paperos/note.txt");
    env=getenv("PAPEROS_APP_ROOT"); copy_text(app.app_root,sizeof(app.app_root),env?env:"/var/lib/paperos/apps");
    env=getenv("PAPEROS_PACKAGES"); copy_text(app.package_root,sizeof(app.package_root),env?env:"/mnt/us/paperos/packages");
    int taps[32][4],tap_count=0;
    for(int i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--help")) { puts("PaperOS native e-ink launcher\n--font FILE --render FILE.pgm --screen home|agents|clock|notes|system|apps|keyboard\n--feed FILE.tsv --url http://HOST:8086/v1/agents.tsv --note FILE --tap X Y\n--app-root DIR --packages DIR --install DIR --remove ID --list-apps --run-app ID\n--standalone (return button for a child application)\n--run-seconds 1..600 --report FILE.json (live device validation)\n--input-method --input-fd N (system input worker)"); return 0; }
        if(!strcmp(argv[i],"--list-apps")) { list_apps=true; continue; }
        if(!strcmp(argv[i],"--standalone")) { app.standalone=true; continue; }
        if(!strcmp(argv[i],"--system-overlay")) { system_overlay_only=true; app.overlay_bridge=true; app.standalone=true; continue; }
        if(!strcmp(argv[i],"--allow-commands")) { app.ui.allow_commands=true; continue; }
        if(!strcmp(argv[i],"--alert-invert")) { app.ui.flash_phase=1; continue; }
        if(!strcmp(argv[i],"--input-method")) { app.screen=INPUT_METHOD; continue; }
        if(!strcmp(argv[i],"--tap") && i+2<argc && tap_count<32) { int x=atoi(argv[++i]),y=atoi(argv[++i]); taps[tap_count][0]=taps[tap_count][2]=x; taps[tap_count][1]=taps[tap_count][3]=y; tap_count++; continue; }
        if(!strcmp(argv[i],"--swipe") && i+4<argc && tap_count<32) { for(int p=0;p<4;p++)taps[tap_count][p]=atoi(argv[++i]); tap_count++; continue; }
        if(i+1>=argc) { fprintf(stderr,"Missing option value\n"); return 2; }
        const char *option=argv[i],*value=argv[++i];
        if(!strcmp(option,"--font")) font_path=value; else if(!strcmp(option,"--render")) render=value;
        else if(!strcmp(option,"--feed")) feed=value; else if(!strcmp(option,"--screen")) { app.screen=parse_screen(value); if(!strcmp(value,"timer")) app.ui.alarm_tab=1; }
#ifdef PAPEROS_NDS
        else if(!strcmp(option,"--nds-rom")){copy_text(app.nds.rom,sizeof(app.nds.rom),value);app.nds.requested=true;app.nds.menu=true;app.screen=NDS_GAME;}
        else if(!strcmp(option,"--nds-data"))copy_text(app.nds.base_data,sizeof(app.nds.base_data),value);
#endif
        else if(!strcmp(option,"--services-file")) setenv("PAPEROS_SERVICE_STATE",value,1);
        else if(!strcmp(option,"--services-socket")) setenv("PAPEROS_SERVICE_SOCKET",value,1);
        else if(!strcmp(option,"--url")) copy_text(app.url,sizeof(app.url),value);
        else if(!strcmp(option,"--note")) copy_text(app.note_path,sizeof(app.note_path),value);
        else if(!strcmp(option,"--muyu-state")) copy_text(app.muyu.path,sizeof(app.muyu.path),value);
        else if(!strcmp(option,"--report")) report=value;
        else if(!strcmp(option,"--app-root")) copy_text(app.app_root,sizeof(app.app_root),value);
        else if(!strcmp(option,"--packages")) copy_text(app.package_root,sizeof(app.package_root),value);
        else if(!strcmp(option,"--install")) install=value;
        else if(!strcmp(option,"--remove")) remove_id=value;
        else if(!strcmp(option,"--run-app")) run_id=value;
        else if(!strcmp(option,"--input-fd")) {
            char *end; long n=strtol(value,&end,10); if(!*value || *end || n<3 || n>255) return 2;
            input_fd=(int)n;
        }
        else if(!strcmp(option,"--run-seconds")) {
            char *end; errno=0; unsigned long duration=strtoul(value,&end,10);
            if(errno || !*value || *end || duration<1 || duration>600) { fprintf(stderr,"Invalid run duration\n"); return 2; }
            run_seconds=(unsigned)duration;
        }
        else { fprintf(stderr,"Unknown option: %s\n",option); return 2; }
    }
    if(render && (run_seconds || report)) { fprintf(stderr,"Live validation options cannot be used with --render\n"); return 2; }
    setenv("PAPEROS_APP_ROOT",app.app_root,1);
    setenv("PAPEROS_PACKAGES",app.package_root,1);
    if(input_fd>=0) {
        if(app.screen!=INPUT_METHOD || !paperos_input_read_request(input_fd,&input_request,2000)) return 2;
        fcntl(input_fd,F_SETFD,FD_CLOEXEC);
    }
    char launcher[1024]; ssize_t launcher_length=readlink("/proc/self/exe",launcher,sizeof(launcher)-1);
    if(launcher_length<0) { fprintf(stderr,"Cannot resolve launcher executable\n"); return 2; } launcher[launcher_length]=0;
    if((install!=NULL)+(remove_id!=NULL)+(run_id!=NULL)+(int)list_apps>1) { fprintf(stderr,"Choose one application operation\n"); return 2; }
    if(install || remove_id) {
        char message[256]; int result=install?paperos_app_install(app.app_root,install,message,sizeof(message)):paperos_app_remove(app.app_root,remove_id,message,sizeof(message));
        fprintf(result?stderr:stdout,"%s\n",message); return result?2:0;
    }
    reload_apps(&app);
    if(list_apps) { for(int i=0;i<app.app_count;i++) printf("%s\t%s\t%s\n",app.apps[i].id,app.apps[i].name,app.apps[i].version); return 0; }
    if(run_id) {
        signal(SIGINT,on_signal); signal(SIGTERM,on_signal); signal(SIGALRM,on_signal);
        if(run_seconds) alarm(run_seconds);
        for(int i=0;i<app.app_count;i++) if(!strcmp(run_id,app.apps[i].id)) {
            int lock=-1; pid_t child=paperos_app_start(app.app_root,&app.apps[i],launcher,font_path,&lock,app.app_message,sizeof(app.app_message));
            if(child<0) { fprintf(stderr,"%s\n",app.app_message); return 2; }
            int status=wait_application(child); close(lock); return status;
        }
        fprintf(stderr,"Application not installed\n"); return 2;
    }
    size_t font_length; font_bytes=read_file(font_path,24*1024*1024,&font_length);
    if(!font_bytes || font_length<32 || !stbtt_InitFont(&font,font_bytes,stbtt_GetFontOffsetForIndex(font_bytes,0))) { fprintf(stderr,"Cannot load font %s\n",font_path); free(font_bytes); return 2; }
    unsigned char *note=read_file(app.note_path,app.screen==INPUT_METHOD?PAPEROS_INPUT_MAX:MAX_NOTE-1,NULL);
    if(note) {
        if(app.screen==INPUT_METHOD && input_fd<0) copy_text(input_request.text,sizeof(input_request.text),(char*)note);
        else copy_text(app.note,sizeof(app.note),(char*)note);
        free(note);
    }
    if(feed) { unsigned char *b=read_file(feed,MAX_BODY,NULL); if(!b || !parse_feed(&app,(char*)b)) { fprintf(stderr,"Invalid agent feed\n"); free(b); free(font_bytes); return 2; } free(b); }
    if(app.url[0] && !fetch_feed(&app)) app.connected=false;
    app.ui.preview=render!=NULL; dash_init(&app);
    if(app.screen==MUYU)muyu_init(&app);
#ifdef PAPEROS_NDS
    if(app.nds.requested){
        if(!app.nds.base_data[0]){env=getenv("PAPEROS_DATA_DIR");copy_text(app.nds.base_data,sizeof(app.nds.base_data),env?env:"/var/lib/paperos/nds");}
        paperos_nds_open(&app.nds);
    }
#endif
    dash_layout(&app);
    if(!render) dash_tick(&app);
    if(system_overlay_only&&!app.ui.services.locked&&!app.ui.services.alert_id[0]&&!app.ui.services.transfer_id[0]) { free(font_bytes); return 0; }
    if(app.screen==INPUT_METHOD) paperos_keyboard_open(&app.keyboard,&input_request,getenv("PAPEROS_IME_HELPER"));
    memset(&input_request,0,sizeof(input_request));
    for(int i=0;i<tap_count;i++) {
        if(taps[i][1]-taps[i][3]>=80) dash_swipe(&app,taps[i][0],taps[i][1],taps[i][2],taps[i][3]);
        else tap(&app,taps[i][2],taps[i][3]);
        if(app.input_requested && render) edit_note(&app);
        if(app.ui.input_task && render) { if(app.ui.allow_commands) dash_input(&app); else app.ui.input_task=0; }
    }
#ifdef PAPEROS_NDS
    if(render&&app.nds.loaded&&!app.nds.menu&&!nds_obscured(&app)){
        for(int i=0;i<6;i++){app.nds.deadline=0;paperos_nds_advance(&app.nds,false);}
    }
#endif
    draw(&app);
    if(render) {
        FILE *f=fopen(render,"wb"); if(!f) { perror(render); finish_input(&app,input_fd,false); free(font_bytes); return 2; }
        fprintf(f,"P5\n%d %d\n255\n",W,H); bool ok=fwrite(pixels,1,sizeof(pixels),f)==sizeof(pixels); if(fclose(f)!=0) ok=false;
        if(!finish_input(&app,input_fd,ok)) ok=false;
#ifdef PAPEROS_NDS
        paperos_nds_close(&app.nds);
#endif
        free(font_bytes); return ok?0:2;
    }
#ifndef HAVE_FBINK
    fprintf(stderr,"Host build only supports --render; use the Kindle build for framebuffer output.\n"); finish_input(&app,input_fd,false); free(font_bytes); return 2;
#else
    signal(SIGINT,on_signal); signal(SIGTERM,on_signal); signal(SIGALRM,on_signal); signal(SIGPIPE,SIG_IGN);
    FBInkConfig cfg={0}; cfg.is_quiet=true; cfg.is_flashing=true;
    int fb=fbink_open(); if(fb<0 || fbink_init(fb,&cfg)<0) { fprintf(stderr,"Framebuffer unavailable\n"); finish_input(&app,input_fd,false); free(font_bytes); return 2; }
    FBInkState state={0}; fbink_get_state(&cfg,&state);
    if(state.screen_width!=W || state.screen_height!=H) { fprintf(stderr,"Expected KT3 600x800 display, got %ux%u\n",state.screen_width,state.screen_height); fbink_close(fb); finish_input(&app,input_fd,false); free(font_bytes); return 2; }
    struct input_absinfo ax={0},ay={0}; bool mt=false; int input=touch_open(getenv("PAPEROS_INPUT_DEVICE"),&ax,&ay,&mt);
    fprintf(stderr,"PaperOS live display: %ux%u; touch=%s mt=%d x=%d..%d y=%d..%d\n",state.screen_width,state.screen_height,input>=0?"present":"missing",mt,ax.minimum,ax.maximum,ay.minimum,ay.maximum);
    int raw_x=0,raw_y=0,start_x=0,start_y=0; touch_position(input,mt,&ax,&ay,&raw_x,&raw_y); bool released=false,touch_started=false,tracking=false,discard_touch=false,painted_lock=false; int frames=0; time_t last_poll=0,last_minute=0;
    unsigned touch_events=0,screen_mask=0,display_errors=0;
#ifdef PAPEROS_NDS
    double nds_panel_at=0;bool nds_was_blocked=false;int nds_input_slot=0;
#endif
    if(run_seconds) alarm(run_seconds);
    app.dirty=true;
    while(!stopped && !app.return_requested && !(app.screen==INPUT_METHOD && app.keyboard.status>=0)) {
        if(!app.ui.services.locked && (app.input_requested || app.ui.input_task)) {
            if(input>=0) close(input);
            input=-1;
            if(app.ui.input_task) dash_input(&app); else edit_note(&app);
            fbink_init(fb,&cfg); input=touch_open(getenv("PAPEROS_INPUT_DEVICE"),&ax,&ay,&mt);
            touch_position(input,mt,&ax,&ay,&raw_x,&raw_y); released=false;tracking=false;touch_started=false; frames=0; app.dirty=true;
        }
        if(!app.ui.services.locked && app.launch_app>=0 && app.launch_app<app.app_count) {
            if(input>=0) close(input);
            input=-1;
            int lock=-1; pid_t child=paperos_app_start(app.app_root,&app.apps[app.launch_app],launcher,font_path,&lock,app.app_message,sizeof(app.app_message));
            app.launch_app=-1;
            if(child>=0) {
                app.apps_launched++; fprintf(stderr,"PaperOS application started: pid=%ld\n",(long)child);
                int status=wait_application(child); close(lock); app.app_returns++;
                fprintf(stderr,"PaperOS application returned: status=%d\n",status);
                snprintf(app.app_message,sizeof(app.app_message),"应用已退出（%d）",status);
            }
            fbink_init(fb,&cfg); input=touch_open(getenv("PAPEROS_INPUT_DEVICE"),&ax,&ay,&mt);
            reload_apps(&app); touch_position(input,mt,&ax,&ay,&raw_x,&raw_y); released=false;tracking=false;touch_started=false; frames=0; app.dirty=true;
        }
        time_t now=time(NULL);
        dash_tick(&app);
        store_tick(&app);
        if(system_overlay_only&&!app.ui.services.locked&&!app.ui.services.alert_id[0]&&!app.ui.services.transfer_id[0]) break;
        if(app.screen==MUYU&&app.muyu.feedback_until>0&&muyu_now()>=app.muyu.feedback_until){app.muyu.feedback_until=0;app.dirty=true;}
#ifdef PAPEROS_NDS
        if(app.screen==NDS_GAME){
            bool blocked=nds_obscured(&app);
            if(blocked&&!nds_was_blocked)paperos_nds_release(&app.nds);
            if(!blocked&&nds_was_blocked)app.nds.deadline=0;
            nds_was_blocked=blocked;
            if(paperos_nds_advance(&app.nds,blocked))app.dirty=true;
        }
#endif
        if(app.ui.display_transition && tracking)discard_touch=true;
        if(now/60!=last_minute) { last_minute=now/60; if(app.ui.services.locked || app.screen==WALLPAPER_FULLSCREEN || app.screen==HOME || app.screen==CLOCK || app.screen==ALARM || app.screen==CALENDAR || app.screen==TIME_SET) app.dirty=true; }
        if(app.url[0] && now-last_poll>=5) { last_poll=now; if(!fetch_feed(&app) && app.connected) { app.connected=false; app.dirty=true; } }
        bool paint_due=true;
#ifdef PAPEROS_NDS
        if(app.screen==NDS_GAME&&!app.nds.menu&&!nds_obscured(&app)&&!app.ui.display_transition&&!app.ui.full_refresh&&frames>0)
            paint_due=paperos_nds_now()-nds_panel_at>=0.25;
#endif
        if(app.dirty&&paint_due) {
            bool manual=app.ui.full_refresh,transition=app.ui.display_transition;
            bool lock_image=app.ui.services.locked&&!app.ui.services.alert_id[0];
            bool clean_lock=lock_image&&(frames==0||!painted_lock||transition);
            if((manual||transition||clean_lock)&&frames>0)fbink_wait_for_complete(fb,LAST_MARKER);
            draw(&app); unsigned refresh_interval=20;
#ifdef PAPEROS_NDS
            if(app.screen==NDS_GAME&&!app.nds.menu&&!nds_obscured(&app))refresh_interval=120;
#endif
            bool periodic=(frames++%refresh_interval==0);
            cfg.is_flashing=manual || transition || clean_lock || periodic || app.ui.services.alert_id[0];
            bool photo_screen=app.screen==LOCK_SETTINGS||app.screen==WALLPAPERS||app.screen==WALLPAPER_PREVIEW||app.screen==WALLPAPER_FULLSCREEN;
            cfg.wfm_mode=(manual||transition||app.ui.services.locked||photo_screen)?WFM_GC16:WFM_AUTO;
            int black=0,white=0;
            if(clean_lock){black=display_solid_phase(fb,0,&cfg);white=display_solid_phase(fb,255,&cfg);}
            screen_mask|=1U<<app.screen;
            int rendered=fbink_print_raw_data(fb,pixels,W,H,sizeof(pixels),0,0,&cfg);
            if(rendered<0) { display_errors++; fprintf(stderr,"Display update failed\n"); }
            else if(frames==1) fprintf(stderr,"PaperOS interface ready\n");
            bool cleaned=true;
            if(clean_lock){
                int image=rendered<0?rendered:fbink_wait_for_complete(fb,LAST_MARKER);
                record_lock_refresh(black,white,image);
                cleaned=black>=0&&white>=0&&image>=0;
                if(black<0||white<0||(image<0&&rendered>=0))display_errors++;
            }
            painted_lock=lock_image&&rendered>=0&&cleaned;
#ifdef PAPEROS_NDS
            if(app.screen==NDS_GAME){nds_panel_at=paperos_nds_now();app.nds.changed=false;}
#endif
            if(painted_lock)record_sleep_ready(&app);
            app.ui.display_transition=false;
            if(manual){
                int completed=rendered<0?rendered:fbink_wait_for_complete(fb,LAST_MARKER);
                FILE *refresh=fopen("/run/paperos/display-refresh.state","w");
                if(refresh){fprintf(refresh,"%s\tGC16_FULL\t%d\t%ld\n",completed<0?"failed":"complete",completed,(long)time(NULL));fclose(refresh);}
                if(completed<0)fprintf(stderr,"Manual full refresh failed: %d\n",completed);
                app.ui.full_refresh=false;
            }
        }
        int poll_ms=250;
#ifdef PAPEROS_NDS
        if(app.screen==NDS_GAME&&app.nds.loaded&&!app.nds.menu&&!nds_obscured(&app)){
            double remaining=app.nds.deadline-paperos_nds_now();poll_ms=remaining<=0?0:(int)(remaining*1000);
            if(poll_ms>17)poll_ms=17;
        }
#endif
        struct pollfd poller={input,POLLIN,0}; if(poll(&poller,input>=0?1:0,poll_ms)<=0) continue;
        struct input_event event;
        while(read(input,&event,sizeof(event))==(ssize_t)sizeof(event)) {
#ifdef PAPEROS_NDS
            if(app.screen==NDS_GAME&&mt&&event.type==EV_ABS){
                if(event.code==ABS_MT_SLOT)nds_input_slot=event.value;
                if(nds_input_slot!=0)continue;
            }
#endif
            if(event.type==EV_ABS && event.code==(mt?ABS_MT_POSITION_X:ABS_X)) raw_x=event.value;
            if(event.type==EV_ABS && event.code==(mt?ABS_MT_POSITION_Y:ABS_Y)) raw_y=event.value;
            if((event.type==EV_KEY && event.code==BTN_TOUCH && event.value==1) || (event.type==EV_ABS && event.code==ABS_MT_TRACKING_ID && event.value>=0)) touch_started=true;
            if(event.type==EV_SYN && event.code==SYN_REPORT && touch_started) {
                start_x=(raw_x-ax.minimum)*W/(ax.maximum-ax.minimum);start_y=(raw_y-ay.minimum)*H/(ay.maximum-ay.minimum);touch_started=false;tracking=true;
            }
            if((event.type==EV_KEY && event.code==BTN_TOUCH && event.value==0) || (event.type==EV_ABS && event.code==ABS_MT_TRACKING_ID && event.value<0)) released=true;
#ifdef PAPEROS_NDS
            if(event.type==EV_SYN&&event.code==SYN_REPORT&&app.screen==NDS_GAME&&!nds_obscured(&app)&&tracking&&!discard_touch){
                int x=(raw_x-ax.minimum)*W/(ax.maximum-ax.minimum),y=(raw_y-ay.minimum)*H/(ay.maximum-ay.minimum);
                if(!released)dash_activity(&app);
                if(paperos_nds_contact(&app.nds,x,y,!released)){
                    if(x>=556&&y<74)app.ui.full_refresh=true;
                    app.ui.display_transition=true;app.dirty=true;
                }
            }
#endif
            if(event.type==EV_SYN && event.code==SYN_REPORT && released) {
                int x=(raw_x-ax.minimum)*W/(ax.maximum-ax.minimum),y=(raw_y-ay.minimum)*H/(ay.maximum-ay.minimum);
                touch_events++;
                if(discard_touch) { /* Consume a contact held across a lock transition. */ }
                else if(app.ui.services.locked && !app.ui.services.alert_id[0]) {
                    if(app.overlay_bridge&&tracking&&abs(y-start_y)<30&&abs(x-start_x)<30)tap(&app,x,y);
                    else if(tracking)dash_swipe(&app,start_x,start_y,x,y);
                } else tap(&app,x,y);
                released=false;tracking=false;discard_touch=false;
                if(report) fprintf(stderr,"PaperOS touch: x=%d y=%d page=%d confirm=%d message=%s\n",x,y,app.screen,app.confirm_remove,app.app_message);
            }
        }
    }
    alarm(0);
    int exit_status=display_errors?2:0;
    if(report) {
        FILE *record=fopen(report,"w");
        if(!record) { perror(report); exit_status=2; }
        else {
            fprintf(record,"{\"width\":%u,\"height\":%u,\"touch_present\":%s,\"multitouch\":%s,\"x_min\":%d,\"x_max\":%d,\"y_min\":%d,\"y_max\":%d,\"frames\":%d,\"display_errors\":%u,\"touch_events\":%u,\"screens_seen\":%u,\"note_saved\":%s,\"apps_installed\":%u,\"apps_removed\":%u,\"apps_launched\":%u,\"app_returns\":%u}\n",state.screen_width,state.screen_height,input>=0?"true":"false",mt?"true":"false",ax.minimum,ax.maximum,ay.minimum,ay.maximum,frames,display_errors,touch_events,screen_mask,app.note_saved?"true":"false",app.apps_installed,app.apps_removed,app.apps_launched,app.app_returns);
            if(fclose(record)) exit_status=2;
        }
    }
    if(input>=0) close(input);
    fbink_close(fb);
#ifdef PAPEROS_NDS
    if(app.nds.requested)fprintf(stderr,"PAPEROS_NDS_SESSION {\"loaded\":%s,\"emulated_frames\":%llu,\"video_frames\":%u,\"last_emulated_fps\":%.3f,\"physical_updates\":%d}\n",app.nds.loaded?"true":"false",(unsigned long long)app.nds.frames,app.nds.video_frames,app.nds.measured_fps,frames);
    if(app.nds.loaded&&!app.nds.skip_exit_save&&!paperos_nds_save(&app.nds,true))exit_status=2;
    paperos_nds_close(&app.nds);
#endif
    if(!finish_input(&app,input_fd,exit_status==0)) exit_status=2;
    free(font_bytes); return app.overlay_return&&exit_status==0?42:exit_status;
#endif
}

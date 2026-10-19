/* Shared native screens. Every PaperOS app, including the keyboard worker,
 * presents pending reminders without discarding its previous UI state. */
static void reload_apps(App *a);
static const char *widget_types[]={"clock","calendar","weather","mihome"};
static const char *widget_names[]={"时间","日期与农历","逐小时天气","室内与设备状态"};
static const char *week_names[]={"星期一","星期二","星期三","星期四","星期五","星期六","星期日"};
static long dash_mono(void) { struct timespec t; clock_gettime(CLOCK_BOOTTIME,&t); return t.tv_sec; }
static void dash_local(struct tm *local) { time_t now=time(NULL); localtime_r(&now,local); }
static int dash_provider(App *a,int kind) {
    for(int i=0;i<a->app_count;i++) if(!strcmp(a->apps[i].widget,widget_types[kind])) return i;
    return -1;
}
static bool dash_command(App *a,const char *name,const char *const *args) {
    if(a->ui.preview && !a->ui.allow_commands) { copy_text(a->ui.message,sizeof(a->ui.message),"预览中不执行系统操作"); return false; }
    bool okay=paperos_service_command(name,args,a->ui.message,sizeof(a->ui.message));
    paperos_services_read(&a->ui.services); a->dirty=true; return okay;
}
static void dash_activity(App *a) {
    if(a->ui.preview || a->ui.services.locked) return;
    long now=dash_mono();
    if(now==a->ui.last_activity)return;
    char ignored[128];paperos_service_command("lock-activity",NULL,ignored,sizeof(ignored));
    a->ui.last_activity=now;
}
static void dash_save_widgets(App *a) {
    char path[768],temporary[800],content[128]; snprintf(path,sizeof(path),"%s/.widgets.conf",a->app_root);
    snprintf(temporary,sizeof(temporary),"%s.tmp.XXXXXX",path); int fd=mkstemp(temporary);
    if(fd<0) { copy_text(a->ui.message,sizeof(a->ui.message),"组件布局保存失败"); return; }
    int length=snprintf(content,sizeof(content),"%d %d %d %d %d\n",a->ui.order[0],a->ui.order[1],a->ui.order[2],a->ui.order[3],a->ui.visible);
    bool okay=write(fd,content,(size_t)length)==length && fsync(fd)==0;
    if(close(fd)) okay=false;
    if(!okay || rename(temporary,path)) { unlink(temporary); copy_text(a->ui.message,sizeof(a->ui.message),"组件布局保存失败"); }
}
static void dash_init(App *a) {
    for(int i=0;i<4;i++) a->ui.order[i]=i;
    a->ui.visible=15; a->ui.duration=1500;
    struct tm local; dash_local(&local);
    a->ui.calendar_year=local.tm_year+1900; a->ui.calendar_month=local.tm_mon+1; a->ui.calendar_day=local.tm_mday;
    char path[768]; snprintf(path,sizeof(path),"%s/.widgets.conf",a->app_root);
    FILE *f=fopen(path,"r");
    if(f) {
        int order[4],bits; unsigned mask=0;
        if(fscanf(f,"%d %d %d %d %d",&order[0],&order[1],&order[2],&order[3],&bits)==5 && bits>=0 && bits<16) {
            for(int i=0;i<4;i++) if(order[i]>=0 && order[i]<4) mask|=1U<<order[i];
            if(mask==15) { memcpy(a->ui.order,order,sizeof(order)); a->ui.visible=bits; }
        }
        fclose(f);
    }
    paperos_services_read(&a->ui.services);
}
static void dash_line(int x0,int y0,int x1,int y1,unsigned char color) {
    int dx=abs(x1-x0),sx=x0<x1?1:-1,dy=-abs(y1-y0),sy=y0<y1?1:-1,err=dx+dy;
    for(;;) { rect(x0,y0,2,2,color); if(x0==x1&&y0==y1) break; int e=2*err; if(e>=dy) {err+=dy;x0+=sx;} if(e<=dx) {err+=dx;y0+=sy;} }
}
static void dash_circle(int cx,int cy,int r,unsigned char color) {
    int x=r,y=0,e=1-r;
    while(x>=y) {
        rect(cx+x,cy+y,2,2,color);rect(cx+y,cy+x,2,2,color);rect(cx-y,cy+x,2,2,color);rect(cx-x,cy+y,2,2,color);
        rect(cx-x,cy-y,2,2,color);rect(cx-y,cy-x,2,2,color);rect(cx+y,cy-x,2,2,color);rect(cx+x,cy-y,2,2,color);
        y++; if(e<0) e+=2*y+1; else {x--;e+=2*(y-x)+1;}
    }
}
static void dash_icon(int kind,int x,int y,int size) {
    int c=x+size/2;
    if(kind==0) { /* home */
        dash_line(x,y+size/2,c,y,0); dash_line(c,y,x+size,y+size/2,0);
        dash_line(x+3,y+size/2,x+3,y+size,0);dash_line(x+size-3,y+size/2,x+size-3,y+size,0);
        dash_line(x+3,y+size,x+size-3,y+size,0); box(c-4,y+size-10,9,11,0);
    } else if(kind==1) {
        for(int r=0;r<2;r++) for(int col=0;col<2;col++) box(x+col*(size/2+2),y+r*(size/2+2),size/2-2,size/2-2,0);
    } else if(kind==2) { dash_circle(c,y+size/2,size/3,0);dash_circle(c,y+size/2,size/8,0);
        for(int i=0;i<8;i++) { double angle=i*3.141592653589793/4; dash_line(c+(int)(cos(angle)*size/3),y+size/2+(int)(sin(angle)*size/3),c+(int)(cos(angle)*size/2),y+size/2+(int)(sin(angle)*size/2),0); }
    } else if(kind==3) { dash_circle(c,y+size/2,size/2-3,0);dash_line(c,y+size/2,c,y+7,0);dash_line(c,y+size/2,c+size/4,y+size*2/3,0); }
    else { dash_circle(c,y+size/2,size/3,0); }
}
static void dash_fit(int x,int y,int maximum,const char *label,int width,unsigned char color) {
    int size=maximum; while(size>16 && text_width(label,size)>width) size--;
    text(x,y,size,label,width,color);
}
static void dash_arc(int cx,int cy,int radius,int from,int to,unsigned char color) {
    int px=0,py=0;
    for(int degrees=from;degrees<=to;degrees+=5){
        double angle=degrees*3.141592653589793/180;
        int x=cx+(int)lround(cos(angle)*radius),y=cy+(int)lround(sin(angle)*radius);
        if(degrees>from)dash_line(px,py,x,y,color);
        px=x;py=y;
    }
}
static void dash_refresh_icon(int cx,int cy) {
    dash_arc(cx,cy,11,35,325,0);
    int x=cx+9,y=cy-6;
    dash_line(x,y,x-7,y-1,0);dash_line(x,y,x+1,y-7,0);
}
static void dash_network_icon(const PaperOSServices *s,int cx,int cy) {
    if(s->airplane){
        dash_line(cx,cy-13,cx,cy+12,0);
        dash_line(cx-14,cy+4,cx,cy-3,0);dash_line(cx,cy-3,cx+14,cy+4,0);
        dash_line(cx-7,cy+12,cx,cy+8,0);dash_line(cx,cy+8,cx+7,cy+12,0);
        return;
    }
    unsigned char ink=s->connected?0:130;
    for(int radius=6;radius<=18;radius+=6)dash_arc(cx,cy+7,radius,220,320,ink);
    rect(cx-1,cy+6,4,4,ink);
    if(!s->connected)dash_line(cx-13,cy-12,cx+13,cy+12,0);
}
static int dash_battery(bool *charging) {
    int capacity=-1;FILE *f=fopen("/sys/class/power_supply/bd7181x_bat/capacity","r");
    if(f){if(fscanf(f,"%d",&capacity)!=1||capacity<0||capacity>100)capacity=-1;fclose(f);}
    *charging=false;f=fopen("/sys/class/power_supply/bd7181x_bat/status","r");
    if(f){char status[32]={0};if(fgets(status,sizeof(status),f))*charging=!strncmp(status,"Charging",8);fclose(f);}
    return capacity;
}
static void dash_status(App *a) {
    text(19,9,25,"PaperOS",180,0);
    dash_refresh_icon(414,24);dash_network_icon(&a->ui.services,478,24);
    bool charging;int capacity=dash_battery(&charging);
    box(533,16,34,18,0);box(534,17,32,16,0);rect(568,21,3,8,0);
    if(capacity>=0)rect(537,20,26*capacity/100,10,0);
    else rect(545,24,10,2,0);
    if(charging){unsigned char ink=capacity>=65?255:0;dash_line(551,19,547,25,ink);dash_line(547,25,553,25,ink);dash_line(553,25,549,31,ink);}
}
static void dash_header(App *a,const char *title,const char *back) {
    dash_status(a); text(19,57,29,back,160,0);
    text((W-text_width(title,38))/2,52,38,title,360,0); rect(18,104,564,1,160);
}
static void dash_toggle(int x,int y,bool on) {
    box(x,y,66,36,0); if(on) rect(x+2,y+2,62,32,0);
    rect(x+(on?35:5),y+5,26,26,on?255:0);
}
static const char *dash_weather_name(int code) {
    if(code==0) return "晴";
    if(code<=3) return "多云";
    if(code<=48) return "雾";
    if(code<=57) return "毛毛雨";
    if(code<=67) return "雨";
    if(code<=77) return "雪";
    if(code<=82) return "阵雨";
    if(code<=86) return "阵雪";
    return "雷雨";
}
static bool dash_cloud_inside(int x,int y,int size) {
    int px=x*100,py=y*100;
    const int circles[3][3]={{27,55,20},{51,38,27},{76,55,19}};
    for(int i=0;i<3;i++){int dx=px-circles[i][0]*size,dy=py-circles[i][1]*size,r=circles[i][2]*size;if(dx*dx+dy*dy<=r*r)return true;}
    return px>=27*size&&px<=76*size&&py>=52*size&&py<=74*size;
}
static void dash_weather_icon(int x,int y,int size,int code) {
    if(code==0) {
        dash_circle(x+size/2,y+size/2,size/4,0);
        for(int i=0;i<8;i++) { double t=i*3.141592653589793/4;dash_line(x+size/2+(int)(cos(t)*size*.36),y+size/2+(int)(sin(t)*size*.36),x+size/2+(int)(cos(t)*size*.48),y+size/2+(int)(sin(t)*size*.48),0); }
    } else {
        for(int row=0;row<size;row++)for(int col=0;col<size;col++)if(dash_cloud_inside(col,row,size)&&
            (!dash_cloud_inside(col-2,row,size)||!dash_cloud_inside(col+2,row,size)||!dash_cloud_inside(col,row-2,size)||!dash_cloud_inside(col,row+2,size)))rect(x+col,y+row,1,1,0);
        if(code>=51) for(int i=0;i<3;i++) dash_line(x+size/3+i*size/6,y+size*4/5,x+size/3+i*size/6-2,y+size-1,0);
    }
}
static int dash_first_hour(const PaperOSServices *s) {
    long target=(long)(time(NULL)/3600)*3600;
    for(int i=0;i<s->hour_count;i++) if(s->hours[i].time>=target) return i;
    return s->hour_count;
}
static void dash_weather_widget(App *a,int y) {
    PaperOSServices *s=&a->ui.services; char b[128];
    dash_fit(19,y+8,35,s->weather_name[0]?s->weather_name:"北京市朝阳区",360,0);
    if(s->weather_fetched>0) {
        snprintf(b,sizeof(b),"%.0f°",s->temperature); dash_weather_icon(408,y+10,44,s->weather_code);text(468,y-2,77,b,115,0);
        snprintf(b,sizeof(b),"%s · 最高%.0f° 最低%.0f°",dash_weather_name(s->weather_code),s->high,s->low);
        text(19,y+55,25,b,400,35);
        text(461,y+65,23,"逐小时 ›",120,0);
        int first=dash_first_hour(s);
        if(first>=s->hour_count) { text(20,y+137,27,"预报已过期，请联网更新",540,70); return; }
        for(int col=0;col<6 && first+col<s->hour_count;col++) {
            PaperOSHour *h=&s->hours[first+col]; int x=20+col*94; struct tm t; time_t stamp=h->time; localtime_r(&stamp,&t);
            snprintf(b,sizeof(b),"%02d时",t.tm_hour);text(x+17,y+103,24,b,89,0);
            dash_weather_icon(x+24,y+137,40,h->code);
            snprintf(b,sizeof(b),"%.0f°",h->temperature);text(x+24,y+180,32,b,85,0);
            snprintf(b,sizeof(b),"%.0f%%",h->rain);text(x+20,y+231,24,b,85,35);
            if(col) rect(x-4,y+104,1,156,205);
        }
        text(20,y+211,19,"降雨概率",100,55);
        time_t stamp=s->weather_fetched; struct tm t; localtime_r(&stamp,&t);
        snprintf(b,sizeof(b),"Open-Meteo · %02d:%02d%s",t.tm_hour,t.tm_min,time(NULL)-stamp>3600?" 缓存":" 更新");
        text(270,y+265,18,b,310,75);
    } else { text(20,y+110,29,s->weather_busy?"正在更新该地区天气":"联网后显示天气",540,55);text(20,y+158,24,"点天气卡片，可查看预报和设置地区",540,75); }
}
#include "mihome.inc"
static void dash_layout(App *a) {
    PaperOSDashboard *u=&a->ui; int kinds[4],n=0,total=0;
    for(int i=0;i<4;i++) { int k=u->order[i]; if((u->visible&(1<<k)) && dash_provider(a,k)>=0) kinds[n++]=k; }
    for(int i=0;i<n;i++) { int k=kinds[i]; total+=(k<2?160:k==2?280:178)+12; if(k<2&&i+1<n&&kinds[i+1]<2) i++; }
    int end=total>660?652:712,y=52,page=0; u->widget_count=0;
    for(int i=0;i<n;i++) {
        int k=kinds[i],height=k<2?160:k==2?280:178;
        bool pair=k<2 && i+1<n && kinds[i+1]<2;
        if(y+height>end) { page++; y=52; }
        u->widgets[u->widget_count++]=(PaperOSWidgetRect){18,y,pair?278:564,height,k,page};
        if(pair) { int next=kinds[++i]; u->widgets[u->widget_count++]=(PaperOSWidgetRect){322,y,260,height,next,page}; }
        y+=height+12;
    }
    u->widget_pages=page+1; if(u->widget_page>=u->widget_pages) u->widget_page=0;
}
static void dash_home(App *a) {
    dash_status(a); dash_layout(a); PaperOSDashboard *u=&a->ui; struct tm local;dash_local(&local);char b[160];
    for(int i=0;i<u->widget_count;i++) {
        PaperOSWidgetRect *r=&u->widgets[i];if(r->page!=u->widget_page) continue;
        if(r->kind==0) {
            strftime(b,sizeof(b),"%H:%M",&local);dash_fit(r->x,r->y-12,154,b,r->w-6,0);
            long next=0; for(int j=0;j<u->services.alarm_count;j++) if(u->services.alarms[j].enabled && (next==0 || u->services.alarms[j].next<next)) next=u->services.alarms[j].next;
            if(next) { time_t t=next;struct tm at;localtime_r(&t,&at);snprintf(b,sizeof(b),"闹钟 %02d:%02d ›",at.tm_hour,at.tm_min); }
            else copy_text(b,sizeof(b),"闹钟与倒计时 ›");
            text(r->x+6,r->y+130,22,b,r->w-10,40);
        } else if(r->kind==1) {
            snprintf(b,sizeof(b),"%d年%d月%d日",local.tm_year+1900,local.tm_mon+1,local.tm_mday);dash_fit(r->x+8,r->y+12,32,b,r->w-8,0);
            text(r->x+8,r->y+55,32,week_names[(local.tm_wday+6)%7],r->w-8,0);
            paperos_lunar_label(local.tm_year+1900,local.tm_mon+1,local.tm_mday,true,b,sizeof(b));dash_fit(r->x+8,r->y+95,24,b,r->w-8,40);
            paperos_calendar_events(local.tm_year+1900,local.tm_mon+1,local.tm_mday,b,sizeof(b));
            if(!b[0])copy_text(b,sizeof(b),"万年历");
            size_t used=strlen(b);if(used+5<sizeof(b))snprintf(b+used,sizeof(b)-used," ›");
            dash_fit(r->x+8,r->y+130,24,b,r->w-8,0);
        } else if(r->kind==2) dash_weather_widget(a,r->y);
        else dash_mihome_widget(a,r->y);
        if(r->x==18) rect(18,r->y+r->h+5,564,1,165);
        else if(r->kind<2) rect(306,r->y+6,1,r->h-18,190);
    }
    if(!u->widget_count) { text(25,210,38,"添加你的首页组件",550,0);text(25,270,26,"安装支持组件的应用后，在这里添加。",550,60);button(25,345,550,56,"添加 Widget",false); }
    if(u->widget_pages>1) {button(20,664,120,44,"上页",false);button(460,664,120,44,"下页",false);snprintf(b,sizeof(b),"%d / %d",u->widget_page+1,u->widget_pages);text(270,672,22,b,120,50);}
}
static void dash_launch(App *a,int kind) {
    int i=dash_provider(a,kind); if(i<0) { copy_text(a->ui.message,sizeof(a->ui.message),"请先安装对应的应用"); return; }
    if(a->ui.preview) { Screen screens[]={ALARM,CALENDAR,WEATHER,MIHOME};a->screen=screens[kind]; }
    else a->launch_app=i;
}
static void dash_widgets(App *a) {
    PaperOSDashboard *u=&a->ui;
    dash_header(a,u->adding_widget?"添加 Widget":"编辑主页","主页");
    if(!u->adding_widget) {
        text(20,122,24,"应用提供组件，按需要显示和排序",560,70);
        for(int row=0;row<4;row++) {
            int kind=u->order[row],provider=dash_provider(a,kind),y=166+row*119;
            text(22,y,29,widget_names[kind],360,0);
            const char *source=provider>=0?a->apps[provider].name:"应用未安装";
            char b[160];snprintf(b,sizeof(b),"来自 %s",source);text(22,y+36,21,b,350,65);
            button(366,y+5,214,45,(u->visible&(1<<kind))?"移除":"添加",false);
            button(365,y+60,102,44,"上移",false);button(478,y+60,102,44,"下移",false);
            rect(20,y+112,560,1,195);
        }
        button(20,659,560,48,"+ 添加 Widget",false);
    } else for(int kind=0;kind<4;kind++) {
        int y=145+kind*125,provider=dash_provider(a,kind);
        text(23,y,30,widget_names[kind],350,0);
        text(23,y+43,23,provider>=0?a->apps[provider].name:"先在应用库安装对应应用",380,65);
        button(410,y+6,170,50,provider<0?"未安装":(u->visible&(1<<kind))?"已添加":"添加",false);
        rect(20,y+111,560,1,190);
    }
}
static void dash_alarm(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;char b[160];struct tm local;dash_local(&local);
    dash_header(a,"闹钟","主页");strftime(b,sizeof(b),"%H:%M",&local);text(20,115,119,b,335,0);
    button(377,139,202,55,"设置时间 ›",false);
    strftime(b,sizeof(b),"%Y年%m月%d日",&local);text(22,215,27,b,390,30);
    button(20,260,275,48,"闹钟",u->alarm_tab==0);button(306,260,274,48,"倒计时",u->alarm_tab==1);
    if(u->alarm_tab==0) {
        for(int row=0;row<2&&u->alarm_page*2+row<s->alarm_count;row++) {
            PaperOSAlarm *alarm=&s->alarms[u->alarm_page*2+row];int y=332+row*113;
            snprintf(b,sizeof(b),"%02d:%02d",alarm->hour,alarm->minute);text(23,y,69,b,350,0);
            const char *repeat=alarm->days==0?"单次":alarm->days==127?"每天":alarm->days==31?"工作日":"自定义";
            snprintf(b,sizeof(b),"%s · %s",repeat,alarm->label);text(24,y+73,24,b,440,55);dash_toggle(501,y+27,alarm->enabled);rect(20,y+106,560,1,180);
        }
        if(!s->alarm_count) {text(22,367,34,"还没有闹钟",540,0);text(22,419,25,"添加一个时间，到点用屏幕提醒。",540,65);}
        button(20,574,560,54,"+ 添加闹钟",false);
        if(s->alarm_count>2) {button(20,639,105,44,"上页",false);button(140,639,105,44,"下页",false);}
        text(300,654,23,"提醒：黑白交替",280,55);
    } else {
        int seconds=(!strcmp(s->timer_state,"running")||!strcmp(s->timer_state,"paused"))?s->remaining:u->duration;
        int values[]={seconds/3600,(seconds/60)%60,seconds%60};
        for(int i=0;i<3;i++){snprintf(b,sizeof(b),"%02d",values[i]);int size=112;while(size>40&&text_width(b,size)>160)size--;text(29+i*188+(164-text_width(b,size))/2,383,size,b,166,0);}
        text(198,389,89,":",40,0);text(386,389,89,":",40,0);
        const char *units[]={"时","分","秒"};
        for(int i=0;i<3;i++){ button(29+i*188,329,164,45,"+",false);text(95+i*188,477,25,units[i],80,55);button(29+i*188,513,164,45,"−",false); }
        const char *presets[]={"5分钟","15分钟","25分钟","60分钟"};for(int i=0;i<4;i++)button(20+i*142,576,132,46,presets[i],false);
        bool running=!strcmp(s->timer_state,"running"),paused=!strcmp(s->timer_state,"paused");
        if(running||paused){button(20,645,275,55,running?"暂停":"继续",true);button(307,645,273,55,"取消计时",false);}
        else button(20,645,560,55,"开始",true);
        text(20,707,18,"切换应用后继续计时",550,70);
    }
    if(u->message[0]) text(22,692,21,u->message,550,0);
}
static void dash_alarm_edit(App *a) {
    PaperOSDashboard *u=&a->ui;char b[180];
    dash_header(a,u->edit_id?"编辑闹钟":"添加闹钟","闹钟");
    const int values[]={u->edit_hour,u->edit_minute};
    for(int i=0;i<2;i++){int x=44+i*274;button(x,150,238,48,"+",false);snprintf(b,sizeof(b),"%02d",values[i]);text(x+55,214,103,b,210,0);button(x,333,238,48,"−",false);}
    text(285,230,74,":",45,0);
    const char *labels[]={"单次","每天","工作日"};
    int masks[]={0,127,31};for(int i=0;i<3;i++)button(20+i*190,414,180,46,labels[i],u->edit_days==masks[i]);
    const char *days[]={"一","二","三","四","五","六","日"};
    for(int i=0;i<7;i++)button(20+i*81,477,73,46,days[i],(u->edit_days&(1<<i))!=0);
    snprintf(b,sizeof(b),"标签：%s",u->edit_label);button(20,546,560,50,b,false);
    button(20,628,u->edit_id?272:560,60,"保存闹钟",true);
    if(u->edit_id)button(306,628,274,60,u->delete_alarm?"确认删除":"删除",false);
    if(u->message[0])text(20,698,21,u->message,550,0);
}
static void dash_begin_time(App *a) {
    struct tm t;dash_local(&t);a->ui.time_year=t.tm_year+1900;a->ui.time_month=t.tm_mon+1;a->ui.time_day=t.tm_mday;a->ui.time_hour=t.tm_hour;a->ui.time_minute=t.tm_min;
    a->ui.time_synced=a->ui.services.time_synced;
    a->ui.return_screen=a->screen;a->screen=TIME_SET;a->ui.message[0]=0;
}
static void dash_time(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;char b[160];dash_header(a,"设置时间","返回");
    text(22,120,24,"北京时间 · UTC+8",540,60);
    text(22,164,31,"自动对时",440,0);dash_toggle(505,168,s->time_auto);
    text(22,208,22,s->time_auto?(s->connected?"联网后定期校准时间":"未联网，连接后自动同步"):"已关闭，可手动设置时间",550,60);
    if(s->time_busy)copy_text(b,sizeof(b),"正在同步…");
    else if(s->time_message[0]&&strcmp(s->time_message,"同步成功"))copy_text(b,sizeof(b),s->time_message);
    else if(s->time_synced){time_t at=s->time_synced;struct tm synced;localtime_r(&at,&synced);strftime(b,sizeof(b),"已同步 %m-%d %H:%M",&synced);}
    else copy_text(b,sizeof(b),s->connected?"尚未同步":"等待联网同步");
    text(22,254,22,b,375,45);button(410,242,170,46,s->time_busy?"同步中…":"立即同步",false);
    rect(20,300,560,1,185);
    if(s->time_synced!=u->time_synced&&s->time_synced){
        struct tm t;dash_local(&t);u->time_year=t.tm_year+1900;u->time_month=t.tm_mon+1;u->time_day=t.tm_mday;u->time_hour=t.tm_hour;u->time_minute=t.tm_min;
        u->time_synced=s->time_synced;
    }
    if(s->time_auto){
        struct tm t;dash_local(&t);strftime(b,sizeof(b),"%H:%M",&t);centered(355,128,b);
        snprintf(b,sizeof(b),"%d年%d月%d日",t.tm_year+1900,t.tm_mon+1,t.tm_mday);centered(500,34,b);
        centered(561,24,"关闭自动对时后可手动设置");
        if(u->message[0])text(20,648,21,u->message,550,0);
        return;
    }
    int values[]={u->time_year,u->time_month,u->time_day,u->time_hour,u->time_minute};const char *labels[]={"年","月","日","时","分"};
    for(int i=0;i<5;i++){
        int x=i<3?20+i*190:40+(i-3)*270,y=i<3?306:480,w=i<3?180:250;
        button(x,y,w,36,"+",false);snprintf(b,sizeof(b),i==0?"%04d":"%02d",values[i]);
        text(x+(w-text_width(b,56))/2,y+44,56,b,w-24,0);
        text(x+(w-text_width(labels[i],22))/2,y+98,22,labels[i],60,55);button(x,y+125,w,36,"−",false);
    }
    button(20,677,560,38,"保存时间",true);
    if(u->message[0])text(20,648,19,u->message,550,0);
}
static void dash_calendar(App *a) {
    PaperOSDashboard *u=&a->ui;char b[160];struct tm t;dash_local(&t);dash_header(a,"万年历","主页");
    strftime(b,sizeof(b),"%H:%M",&t);text(22,111,119,b,550,0);
    paperos_calendar_events(u->calendar_year,u->calendar_month,u->calendar_day,b,sizeof(b));
    if(b[0]){
        text(319,124,21,"当日节气与节日",262,60);
        dash_fit(319,160,28,b,262,0);
    }else{
        int year,month,day,until;const char *next=paperos_next_solar_term(u->calendar_year,u->calendar_month,u->calendar_day,&year,&month,&day,&until);
        text(319,124,21,"下一个节气",262,60);
        if(next[0]){
            snprintf(b,sizeof(b),"%s · %d月%d日",next,month,day);dash_fit(319,160,28,b,262,0);
            snprintf(b,sizeof(b),"%d天后",until);text(319,196,20,b,262,60);
        }
    }
    snprintf(b,sizeof(b),"%d年%d月%d日  %s",u->calendar_year,u->calendar_month,u->calendar_day,week_names[paperos_weekday(u->calendar_year,u->calendar_month,u->calendar_day)]);
    text(22,215,27,b,555,0);paperos_lunar_label(u->calendar_year,u->calendar_month,u->calendar_day,true,b,sizeof(b));text(22,255,24,b,555,60);
    rect(20,296,560,1,170);button(20,310,70,45,"‹",false);button(390,310,70,45,"›",false);button(480,310,100,45,"今天",false);
    snprintf(b,sizeof(b),"%d年%d月",u->calendar_year,u->calendar_month);text(153,317,32,b,235,0);
    const char *week[]={"一","二","三","四","五","六","日"};for(int i=0;i<7;i++)text(20+i*81+(73-text_width(week[i],25))/2,369,25,week[i],74,0);
    int first=paperos_weekday(u->calendar_year,u->calendar_month,1),days=paperos_month_days(u->calendar_year,u->calendar_month);
    for(int cell=0;cell<42;cell++){
        int day=cell-first+1;if(day<1||day>days)continue;
        int x=20+(cell%7)*81,y=411+(cell/7)*49;bool selected=day==u->calendar_day;if(selected)rect(x,y,73,47,0);
        snprintf(b,sizeof(b),"%d",day);text(x+(73-text_width(b,29))/2,y+1,29,b,73,selected?255:0);
        paperos_festival_label(u->calendar_year,u->calendar_month,day,b,sizeof(b));
        char *separator=strstr(b," · ");bool multiple=separator!=NULL;if(separator)*separator=0;
        const char *term=paperos_solar_term(u->calendar_year,u->calendar_month,day);
        bool special=b[0]||term[0];
        if(!b[0]&&term[0])copy_text(b,sizeof(b),term);
        else if(b[0]&&term[0])multiple=true;
        if(!b[0])paperos_lunar_label(u->calendar_year,u->calendar_month,day,false,b,sizeof(b));
        int label_size=special?20:18;while(label_size>16&&text_width(b,label_size)>71)label_size--;
        text(x+(73-text_width(b,label_size))/2,y+29,label_size,b,73,selected?255:special?0:75);
        if(multiple)rect(x+65,y+7,3,3,selected?255:0);
    }
}
static void dash_weather(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;char b[320];dash_header(a,"天气","主页");
    dash_fit(20,122,37,s->weather_name[0]?s->weather_name:"北京市朝阳区",390,0);button(430,118,150,46,"地区设置",false);
    text(22,165,18,s->weather_area,550,60);
    if(s->weather_fetched<=0){
        text(22,250,35,s->weather_busy?"正在更新该地区天气":"尚无该地区天气",550,0);text(22,310,24,s->weather_message[0]?s->weather_message:"连接 Wi-Fi 后更新",550,70);
        button(20,420,273,52,"前往网络设置",false);button(307,420,273,52,"更新天气",false);return;
    }
    snprintf(b,sizeof(b),"%.0f° · %s",s->temperature,dash_weather_name(s->weather_code));text(22,190,50,b,550,0);
    snprintf(b,sizeof(b),"最高 %.0f° / 最低 %.0f°",s->high,s->low);text(22,245,25,b,550,65);
    text(20,293,22,"时间",151,65);text(174,293,22,"天气",100,65);text(292,293,22,"温度",90,65);text(388,293,22,"降雨",90,65);text(479,293,22,"风速",105,65);
    int first=dash_first_hour(s)+u->weather_page*6;
    for(int row=0;row<6&&first+row<s->hour_count;row++){
        PaperOSHour *h=&s->hours[first+row];int y=332+row*50;time_t stamp=h->time;struct tm t;localtime_r(&stamp,&t);
        snprintf(b,sizeof(b),"%02d日 %02d时",t.tm_mday,t.tm_hour);text(20,y+6,23,b,151,0);
        text(174,y+6,23,dash_weather_name(h->code),100,0);snprintf(b,sizeof(b),"%.0f°",h->temperature);text(292,y+6,26,b,90,0);
        snprintf(b,sizeof(b),"%.0f%%",h->rain);text(388,y+6,24,b,90,0);snprintf(b,sizeof(b),"%.0fkm/h",h->wind);text(479,y+6,22,b,105,0);
        rect(20,y+45,560,1,205);
    }
    button(20,647,110,46,"上页",false);button(145,647,110,46,"下页",false);button(422,647,158,46,s->weather_busy?"正在更新…":"更新天气",false);
    time_t stamp=s->weather_fetched;struct tm t;localtime_r(&stamp,&t);snprintf(b,sizeof(b),"Open-Meteo · %02d-%02d %02d:%02d%s%s",t.tm_mon+1,t.tm_mday,t.tm_hour,t.tm_min,strcmp(s->weather_message,"Open-Meteo")?" · ":"",strcmp(s->weather_message,"Open-Meteo")?s->weather_message:"");
    text(20,701,19,b,560,70);
}
#include "weather.inc"
#include "battery.inc"
static void dash_settings(App *a) {
    PaperOSServices *s=&a->ui.services;dash_header(a,"设置","主页");
    text(22,143,32,"Wi-Fi",500,0);text(22,185,23,s->connected?s->ssid:s->wifi?"未连接":"已关闭",430,65);text(550,156,32,"›",40,0);rect(20,222,560,1,190);
    text(22,241,31,"飞行模式",420,0);dash_toggle(505,245,s->airplane);rect(20,300,560,1,190);
    text(22,320,31,"接收应用",420,0);text(22,358,23,s->receiving?"已开启 · 10分钟内有效":"Wi-Fi 或 Tailscale · 屏幕确认",465,65);dash_toggle(505,325,s->receiving);rect(20,399,560,1,190);
    const char *labels[]={"设置时间","首页组件","锁屏与壁纸","系统信息","电量与续航","Tailscale"};
    for(int i=0;i<6;i++){int y=412+i*48;text(22,y,27,labels[i],510,0);text(550,y,27,"›",40,0);rect(20,y+44,560,1,190);}
    if(a->ui.message[0])text(22,704,16,a->ui.message,550,0);
    else if(s->connected){char b[180];if(s->tailnet_connected)snprintf(b,sizeof(b),"Wi-Fi %s · Tailscale %s",s->ip,s->tailnet_ip);else snprintf(b,sizeof(b),"Wi-Fi %s · 接收端口 8765",s->ip);text(22,704,16,b,550,65);}
}
static void dash_tailnet(App *a) {
    PaperOSServices *s=&a->ui.services;char b[160];dash_header(a,"Tailscale","设置");
    text(22,132,31,"私网连接",420,0);dash_toggle(505,132,s->tailnet_enabled);
    const char *status=!s->tailnet_installed?"尚未安装客户端":s->tailnet_busy?"正在更新连接状态…":!s->tailnet_enabled?"已关闭":!s->connected?"等待 Wi-Fi 联网":s->tailnet_message;
    text(22,184,24,status&&*status?status:"正在连接私有网络",550,65);rect(20,231,560,1,190);
    text(22,252,22,"设备名称",550,65);text(22,289,31,s->tailnet_name[0]?s->tailnet_name:"连接后显示",550,0);
    text(22,343,22,"Tailscale 地址",550,65);text(22,380,34,s->tailnet_ip[0]?s->tailnet_ip:"连接后显示",550,0);
    if(s->tailnet_version[0]){snprintf(b,sizeof(b),"客户端 %s",s->tailnet_version);text(22,424,18,b,550,65);}rect(20,458,560,1,190);
    text(22,482,27,"允许远程接收应用",450,0);dash_toggle(505,480,s->tailnet_receive);
    const char *receive=!s->tailnet_receive?"仅通过当前 Wi-Fi 接收":!s->tailnet_connected?"连接 Tailscale 后可跨网络接收":!s->receiving?"请先在设置中开启「接收应用」":s->tailnet_ready?"远程接收已就绪 · 十分钟内有效":"正在开启远程接收…";
    text(22,535,22,receive,550,65);text(22,573,22,"每次仍需在 Kindle 核对并确认。",550,65);
    button(20,622,560,52,"刷新连接状态",true);
    text(22,692,18,a->ui.message[0]?a->ui.message:"关闭私网连接会暂停远程米家读数。",550,65);
}
#include "wallpaper.inc"
static void dash_network(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;dash_header(a,"Wi-Fi","设置");
    text(22,130,32,"无线网络",420,0);dash_toggle(505,132,s->wifi&&!s->airplane);
    text(22,179,23,s->airplane?"飞行模式已开启":s->connected?s->ssid:s->wifi?"选择要连接的网络":"无线已关闭",535,65);
    if(s->connected){char b[96];snprintf(b,sizeof(b),"IP %s",s->ip);text(22,211,23,b,540,0);}
    button(20,248,182,46,"附近网络",!u->network_saved);button(214,248,182,46,"已保存",u->network_saved);button(414,248,166,46,"扫描网络",false);
    int count=u->network_saved?s->saved_network_count:s->network_count;
    PaperOSWiFi *rows=u->network_saved?s->saved_networks:s->networks;
    if(u->network_page*4>=count)u->network_page=count?(count-1)/4:0;
    for(int row=0;row<4&&u->network_page*4+row<count;row++){
        PaperOSWiFi *w=&rows[u->network_page*4+row];int y=316+row*77;text(22,y,30,w->ssid,510,0);
        char b[144];
        if(w->current)snprintf(b,sizeof(b),"已连接 · 已保存");
        else if(u->network_saved)snprintf(b,sizeof(b),"已保存 · %s",w->available?"在附近":"不在附近");
        else snprintf(b,sizeof(b),"%s · %s信号 %ddBm",w->security,w->saved?"已保存 · ":"",w->level);
        text(22,y+39,22,b,510,65);text(550,y+15,28,"›",40,0);rect(20,y+69,560,1,195);
    }
    if(!count)text(22,351,25,u->network_saved?"连接过的网络会保存在这里":s->busy?"正在搜索附近网络…":"点“扫描网络”查找附近的 Wi-Fi",550,60);
    button(20,645,116,46,"上页",false);button(150,645,116,46,"下页",false);
    text(22,700,20,u->message[0]?u->message:s->net_message,550,50);
}
static void dash_network_profile(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSWiFi *w=&u->network_selected;dash_header(a,"已保存的网络","Wi-Fi");
    text(22,145,36,w->ssid,550,0);
    text(22,205,23,!strcmp(u->services.ssid,w->ssid)&&u->services.connected?"当前已连接":"密码保存在本机，无需重复输入",550,65);
    button(20,306,560,62,"连接此网络",true);
    button(20,394,560,62,"重新输入密码",false);
    button(20,482,560,62,u->network_forget_confirm?"再次点击，确认忘记":"忘记此网络",false);
    text(22,586,22,"其他已保存的网络仍会自动连接。",550,65);
    text(22,680,21,u->message[0]?u->message:u->services.net_message,550,50);
}
static void dash_overlay(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;char b[160];
    if(s->alert_id[0]){
        dash_icon(3,264,113,72);centered(242,52,!strcmp(s->alert_kind,"timer")?"倒计时结束":"闹钟提醒");
        if(!strcmp(s->alert_kind,"timer"))copy_text(b,sizeof(b),"00:00");else{struct tm t;dash_local(&t);strftime(b,sizeof(b),"%H:%M",&t);}
        centered(335,133,b);centered(491,30,!strcmp(s->alert_kind,"timer")?"计时已完成":s->alert_label);
        button(20,635,273,65,"停止",true);button(307,635,273,65,"稍后5分钟",false);
        if(u->flash_phase&1)for(size_t i=0;i<sizeof(pixels);i++)pixels[i]=255-pixels[i];
    }else{
        centered(74,45,"接收应用");text(24,163,37,s->transfer_name,552,0);
        snprintf(b,sizeof(b),"版本 %s",s->transfer_version);text(24,218,27,b,552,50);
        snprintf(b,sizeof(b),"发送方 %s",s->transfer_peer);text(24,265,25,b,552,50);
        centered(341,27,"核对电脑上显示的校验码");centered(393,101,s->transfer_code);
        text(24,524,25,"确认后放入应用库，由你选择安装。",552,55);
        button(20,635,273,65,"拒绝",false);button(307,635,273,65,"确认接收",true);
    }
}
static bool dash_tick(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices next={0};bool changed=false;
    if(paperos_services_read(&next)){
        int remaining=u->services.remaining;
        if(a->screen!=ALARM && !next.alert_id[0] && remaining/60==next.remaining/60)u->services.remaining=next.remaining;
        bool transition=next.locked!=u->services.locked || (next.locked&&strcmp(next.wallpaper_path,u->services.wallpaper_path));
        bool sleep_before=!strcmp(u->services.sleep_phase,"preparing"),sleep_after=!strcmp(next.sleep_phase,"preparing");
        if(next.locked&&(sleep_before!=sleep_after||(sleep_after&&next.sleep_cycle!=u->services.sleep_cycle)))transition=true;
        if(memcmp(&next,&u->services,sizeof(next))){u->services=next;if(!next.locked||transition)changed=true;}
        if(transition)u->display_transition=true;
    }
    if(strcmp(u->alert_seen,u->services.alert_id)){
        copy_text(u->alert_seen,sizeof(u->alert_seen),u->services.alert_id);u->alert_started=dash_mono();u->flash_phase=0;changed=true;if(u->services.locked)u->display_transition=true;
    }
    if(u->services.alert_id[0]){long phase=(dash_mono()-u->alert_started)/2;if(phase!=u->flash_phase){u->flash_phase=phase;changed=true;}}
    if(changed)a->dirty=true;
    return changed;
}
static void dash_swipe(App *a,int x0,int y0,int x1,int y1) {
    if(!a->ui.preview || a->ui.allow_commands)dash_tick(a);
    if(a->ui.services.locked && !a->ui.services.alert_id[0] && y0>=160 && y0-y1>=80 && abs(x1-x0)<200){
        dash_command(a,"lock-unlock",NULL);a->ui.display_transition=true;
    }
}
static void dash_edit_alarm(App *a,int index) {
    PaperOSDashboard *u=&a->ui;u->edit_id=0;u->edit_hour=7;u->edit_minute=30;u->edit_days=31;u->delete_alarm=false;copy_text(u->edit_label,sizeof(u->edit_label),"闹钟");u->message[0]=0;
    if(index>=0 && index<u->services.alarm_count){PaperOSAlarm *s=&u->services.alarms[index];u->edit_id=s->id;u->edit_hour=s->hour;u->edit_minute=s->minute;u->edit_days=s->days;copy_text(u->edit_label,sizeof(u->edit_label),s->label);}
    a->screen=ALARM_EDIT;
}
static bool dash_tap(App *a,int x,int y) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;char b[128],h[32],m[32],d[32];
    if(s->alert_id[0]||s->transfer_id[0]){
        if(y>=635&&y<710){if(s->alert_id[0]){const char *args[]={"id",s->alert_id,NULL};dash_command(a,x<300?"alert-stop":"alert-snooze",args);}else{const char *args[]={"id",s->transfer_id,NULL};dash_command(a,x<300?"receive-reject":"receive-approve",args);}}
        return true;
    }
    if(y<48&&x>=390&&x<438){u->full_refresh=true;return true;}
    if(y<48&&x>=520){a->screen=BATTERY;return true;}
    if(a->screen==HOME){
        if(y>=664&&u->widget_pages>1){if(x<150&&u->widget_page>0)u->widget_page--;if(x>450&&u->widget_page+1<u->widget_pages)u->widget_page++;return true;}
        if(!u->widget_count&&y>=345&&y<405){a->screen=WIDGETS;u->adding_widget=true;return true;}
        for(int i=0;i<u->widget_count;i++){PaperOSWidgetRect *r=&u->widgets[i];if(r->page==u->widget_page&&x>=r->x&&x<r->x+r->w&&y>=r->y&&y<r->y+r->h){dash_launch(a,r->kind);return true;}}
        return true;
    }
    if(y>=48&&y<105&&x<180){
        if(a->screen==NETWORK_PROFILE){a->screen=NETWORK;u->message[0]=0;return true;}
        if(a->screen==BATTERY){a->screen=SETTINGS;return true;}
        if(a->screen==POWER_SETTINGS){a->screen=LOCK_SETTINGS;return true;}
        if(a->screen==WEATHER_COORDINATES){a->screen=WEATHER_LOCATION;u->message[0]=0;return true;}
        if(a->screen==WEATHER_LOCATION){a->screen=WEATHER;u->message[0]=0;return true;}
        if(a->screen==WALLPAPER_PREVIEW){a->screen=WALLPAPERS;return true;}
        if(a->screen==WALLPAPERS){a->screen=LOCK_SETTINGS;return true;}
        if(a->screen==ALARM_EDIT){a->screen=ALARM;return true;}
        if(a->screen==TIME_SET){a->screen=(Screen)u->return_screen;return true;}
        if(a->screen==NETWORK||a->screen==LOCK_SETTINGS||a->screen==TAILNET){a->screen=SETTINGS;return true;}
        if(a->screen==WIDGETS&&u->adding_widget){u->adding_widget=false;return true;}
        if(a->screen==ALARM||a->screen==CALENDAR||a->screen==WEATHER||a->screen==MIHOME||a->screen==SETTINGS||a->screen==WIDGETS){if(a->standalone)a->return_requested=true;else a->screen=HOME;return true;}
    }
    if(a->screen==WIDGETS){
        if(u->adding_widget){int k=(y-145)/125;if(y>=145&&k<4&&x>=400&&dash_provider(a,k)>=0){u->visible|=1<<k;dash_save_widgets(a);u->adding_widget=false;}return true;}
        if(y>=659&&y<712){u->adding_widget=true;return true;}
        int row=(y-166)/119;if(y>=166&&row<4&&x>=360){
            int relative=(y-166)%119,k=u->order[row];
            if(relative<54&&dash_provider(a,k)>=0){u->visible^=1<<k;dash_save_widgets(a);}
            else if(relative>=60&&relative<108){int other=row+(x<473?-1:1);if(other>=0&&other<4){int temp=u->order[other];u->order[other]=k;u->order[row]=temp;dash_save_widgets(a);}}
        }return true;
    }
    if(a->screen==ALARM){
        if(y>=139&&y<202&&x>=370){dash_begin_time(a);return true;}
        if(y>=260&&y<308){u->alarm_tab=x>=300;return true;}
        if(u->alarm_tab==0){
            if(y>=332&&y<558){int row=(y-332)/113,index=u->alarm_page*2+row;if(index<s->alarm_count){if(x>=475){snprintf(b,sizeof(b),"%d",s->alarms[index].id);const char *args[]={"id",b,NULL};dash_command(a,"alarm-toggle",args);}else dash_edit_alarm(a,index);}}
            else if(y>=574&&y<628)dash_edit_alarm(a,-1);
            else if(y>=639&&y<683){if(x<130&&u->alarm_page>0)u->alarm_page--;else if(x<250&&(u->alarm_page+1)*2<s->alarm_count)u->alarm_page++;}
        }else{
            bool active=!strcmp(s->timer_state,"running")||!strcmp(s->timer_state,"paused");
            if(!active&&((y>=329&&y<374)||(y>=513&&y<558))){int col=x/200,delta=(col==0?3600:col==1?60:1)*(y<400?1:-1);u->duration+=delta;if(u->duration<1)u->duration=1;if(u->duration>604799)u->duration=604799;}
            else if(!active&&y>=576&&y<622){int preset[]={300,900,1500,3600};int col=x/150;if(col<4)u->duration=preset[col];}
            else if(y>=645&&y<700){if(active){dash_command(a,x>=300?"timer-cancel":!strcmp(s->timer_state,"running")?"timer-pause":"timer-resume",NULL);}else{snprintf(b,sizeof(b),"%d",u->duration);const char *args[]={"seconds",b,NULL};dash_command(a,"timer-start",args);}}
        }return true;
    }
    if(a->screen==ALARM_EDIT){
        if((y>=150&&y<198)||(y>=333&&y<381)){int sign=y<250?1:-1;if(x<300)u->edit_hour=(u->edit_hour+sign+24)%24;else u->edit_minute=(u->edit_minute+sign+60)%60;}
        else if(y>=414&&y<460){int masks[]={0,127,31};int col=x/200;if(col<3)u->edit_days=masks[col];}
        else if(y>=477&&y<523){int col=(x-20)/81;if(col>=0&&col<7)u->edit_days^=1<<col;}
        else if(y>=546&&y<596)u->input_task=2;
        else if(y>=628&&y<688){
            snprintf(b,sizeof(b),"%d",u->edit_id);const char *idargs[]={"id",b,NULL};
            if(x>=306&&u->edit_id){if(u->delete_alarm){if(dash_command(a,"alarm-remove",idargs))a->screen=ALARM;}else u->delete_alarm=true;}
            else{snprintf(h,sizeof(h),"%d",u->edit_hour);snprintf(m,sizeof(m),"%d",u->edit_minute);snprintf(d,sizeof(d),"%d",u->edit_days);const char *args[]={"id",b,"hour",h,"minute",m,"days",d,"label",u->edit_label,"enabled","true",NULL};if(dash_command(a,"alarm-save",args))a->screen=ALARM;}
        }return true;
    }
    if(a->screen==TIME_SET){
        if(y>=160&&y<205){const char *args[]={"enabled",s->time_auto?"false":"true",NULL};dash_command(a,"time-auto",args);return true;}
        if(y>=242&&y<288&&x>=410){dash_command(a,"time-sync",NULL);return true;}
        if(s->time_auto)return true;
        if(y>=677&&y<715){snprintf(b,sizeof(b),"%04d-%02d-%02d %02d:%02d",u->time_year,u->time_month,u->time_day,u->time_hour,u->time_minute);const char *args[]={"value",b,NULL};if(dash_command(a,"time-set",args))a->screen=(Screen)u->return_screen;return true;}
        int index=-1,sign=0;
        if((y>=306&&y<342)||(y>=431&&y<467)){index=x/200;sign=y<400?1:-1;}
        else if((y>=480&&y<516)||(y>=605&&y<641)){index=x<300?3:4;sign=y<550?1:-1;}
        if(index==0){u->time_year+=sign;if(u->time_year<2000)u->time_year=2000;if(u->time_year>2100)u->time_year=2100;}
        if(index==1)u->time_month=(u->time_month-1+sign+12)%12+1;
        if(index==2){int days=paperos_month_days(u->time_year,u->time_month);u->time_day=(u->time_day-1+sign+days)%days+1;}
        if(index==3)u->time_hour=(u->time_hour+sign+24)%24;
        if(index==4)u->time_minute=(u->time_minute+sign+60)%60;
        int days=paperos_month_days(u->time_year,u->time_month);if(u->time_day>days)u->time_day=days;
        return true;
    }
    if(a->screen==CALENDAR){
        if(y>=310&&y<355){if(x>=480){struct tm t;dash_local(&t);u->calendar_year=t.tm_year+1900;u->calendar_month=t.tm_mon+1;u->calendar_day=t.tm_mday;}
            else if(x<90||x>=390){
                int next=(u->calendar_year-1901)*12+u->calendar_month-1+(x<90?-1:1);
                if(next>=0&&next<200*12){u->calendar_year=1901+next/12;u->calendar_month=next%12+1;u->calendar_day=1;}
            }}
        else if(y>=411&&y<705){int day=((y-411)/49)*7+(x-20)/81-paperos_weekday(u->calendar_year,u->calendar_month,1)+1;if(x>=20&&day>=1&&day<=paperos_month_days(u->calendar_year,u->calendar_month))u->calendar_day=day;}
        return true;
    }
    if(a->screen==WEATHER){
        if(y>=118&&y<164&&x>=430){dash_begin_weather_location(a);return true;}
        if(s->weather_fetched<=0&&y>=420&&y<472){if(x<300)a->screen=NETWORK;else dash_command(a,"weather-refresh",NULL);return true;}
        if(y>=647&&y<693){if(x<130&&u->weather_page>0)u->weather_page--;else if(x>=145&&x<255&&dash_first_hour(s)+(u->weather_page+1)*6<s->hour_count)u->weather_page++;else if(x>=422)dash_command(a,"weather-refresh",NULL);}
        return true;
    }
    if(dash_weather_location_tap(a,x,y))return true;
    if(a->screen==MIHOME){
        if(y>=127&&y<171&&x>=430)dash_command(a,"mihome-refresh",NULL);
        else if(y>=198&&y<244){u->home_tab=x>=300;u->home_page=0;}
        else if(y>=651&&y<695){if(x<140&&u->home_page>0)u->home_page--;else if(x>=150&&x<270&&u->home_page<5)u->home_page++;}
        return true;
    }
    if(a->screen==BATTERY){if(y>=239&&y<285)u->battery_tab=x>=300;return true;}
    if(dash_wallpaper_tap(a,x,y))return true;
    if(a->screen==POWER_SETTINGS){
        if(y>=137&&y<183&&x>=450){const char *args[]={"enabled",s->sleep_enabled?"false":"true",NULL};dash_command(a,"sleep-enable",args);}
        else if(y>=296&&y<342&&x>=20&&x<580){int col=(x-20)/143;const char *times[]={"2","3","5","10"};if(col<4&&(x-20)%143<131){const char *args[]={"times",times[col],NULL};dash_command(a,"lock-powered-multiplier",args);}}
        else if(y>=644&&y<692&&!s->external_power)dash_command(a,"sleep-now",NULL);
        return true;
    }
    if(a->screen==SETTINGS){
        if(y>=130&&y<222){a->screen=NETWORK;dash_command(a,"network-scan",NULL);}
        else if(y>=230&&y<300){const char *args[]={"enabled",s->airplane?"false":"true",NULL};dash_command(a,"airplane",args);}
        else if(y>=313&&y<399){const char *args[]={"enabled",s->receiving?"false":"true",NULL};dash_command(a,"receive-enable",args);if(u->message[0])copy_text(s->net_message,sizeof(s->net_message),u->message);}
        else if(y>=412&&y<700){int row=(y-412)/48;if(row==0)dash_begin_time(a);if(row==1){a->screen=WIDGETS;u->adding_widget=false;}if(row==2)a->screen=LOCK_SETTINGS;if(row==3)a->screen=SYSTEM;if(row==4)a->screen=BATTERY;if(row==5){a->screen=TAILNET;u->message[0]=0;dash_command(a,"tailnet-refresh",NULL);}}
        return true;
    }
    if(a->screen==TAILNET){
        if(y>=125&&y<175&&x>=450){const char *args[]={"enabled",s->tailnet_enabled?"false":"true",NULL};dash_command(a,"tailnet-enable",args);}
        else if(y>=474&&y<526&&x>=450){const char *args[]={"enabled",s->tailnet_receive?"false":"true",NULL};dash_command(a,"tailnet-receive",args);}
        else if(y>=622&&y<674)dash_command(a,"tailnet-refresh",NULL);
        return true;
    }
    if(a->screen==NETWORK){
        if(y>=125&&y<170&&x>=450){const char *args[]={"enabled",s->wifi&&!s->airplane?"false":"true",NULL};dash_command(a,"network-enable",args);}
        else if(y>=248&&y<294){if(x>=400)dash_command(a,"network-scan",NULL);else{u->network_saved=x>=210;u->network_page=0;u->message[0]=0;}}
        else if(y>=316&&y<624){int index=u->network_page*4+(y-316)/77;int count=u->network_saved?s->saved_network_count:s->network_count;PaperOSWiFi *rows=u->network_saved?s->saved_networks:s->networks;if(index<count){PaperOSWiFi *w=&rows[index];u->selected_network=index;u->network_selected=*w;u->message[0]=0;if(w->saved){a->screen=NETWORK_PROFILE;u->network_forget_confirm=false;}else if(!strcmp(w->security,"企业认证"))copy_text(u->message,sizeof(u->message),"此网络需要企业认证，当前暂不支持");else if(!strcmp(w->security,"开放")){const char *args[]={"ssid",w->hex,"password","",NULL};dash_command(a,"network-connect",args);}else u->input_task=1;}}
        else if(y>=645&&y<691){int count=u->network_saved?s->saved_network_count:s->network_count;if(x<140&&u->network_page>0)u->network_page--;else if(x>=150&&x<266&&(u->network_page+1)*4<count)u->network_page++;}
        return true;
    }
    if(a->screen==NETWORK_PROFILE){
        if(y>=306&&y<368){const char *args[]={"ssid",u->network_selected.hex,"saved","true",NULL};dash_command(a,"network-connect",args);u->network_forget_confirm=false;}
        else if(y>=394&&y<456){u->input_task=1;u->network_forget_confirm=false;}
        else if(y>=482&&y<544){if(u->network_forget_confirm){const char *args[]={"ssid",u->network_selected.hex,NULL};if(dash_command(a,"network-forget",args)){a->screen=NETWORK;u->network_page=0;}}else u->network_forget_confirm=true;}
        return true;
    }
    return false;
}
static void dash_input(App *a) {
    PaperOSDashboard *u=&a->ui;int task=u->input_task;u->input_task=0;
    if(task==1 && u->network_selected.hex[0]){
        PaperOSWiFi network=u->network_selected;char password[80]={0};
        int status=paperos_input_text("输入 Wi-Fi 密码","",PAPEROS_INPUT_PASSWORD|PAPEROS_INPUT_ENGLISH,password,sizeof(password));
        if(status==PAPEROS_INPUT_ACCEPTED){const char *args[]={"ssid",network.hex,"password",password,NULL};dash_command(a,"network-connect",args);}
        else copy_text(u->message,sizeof(u->message),status==PAPEROS_INPUT_CANCELLED?"已取消连接":"系统输入法暂不可用");
        memset(password,0,sizeof(password));
    }else if(task==2){int status=paperos_input_text("闹钟标签",u->edit_label,0,u->edit_label,sizeof(u->edit_label));if(status!=PAPEROS_INPUT_ACCEPTED&&status!=PAPEROS_INPUT_CANCELLED)copy_text(u->message,sizeof(u->message),"系统输入法暂不可用");}
    else if(task>=3&&task<=6)dash_weather_input(a,task);
    else if(task>=10&&task<=12)store_input(a,task);
    a->dirty=true;
}

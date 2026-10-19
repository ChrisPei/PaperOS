static void dash_home_data(App *a){
    PaperOSServices *s=&a->ui.services;PaperOSHome *h=&a->ui.home;
    if(!h->available||h->revision!=s->home_revision){if(!paperos_home_read(h,s->home_catalog,s->home_revision))memset(h,0,sizeof(*h));}
}
static PaperOSHomeItem *dash_home_metric(App *a,const char *kind){
    for(int i=0;i<a->ui.home.count;i++)if(!strcmp(a->ui.home.items[i].kind,kind))return &a->ui.home.items[i];
    return NULL;
}
static void dash_mihome_widget(App *a,int y){
    PaperOSServices *s=&a->ui.services;char b[256];dash_home_data(a);
    text(20,y+4,35,"米家",280,0);text(452,y+12,23,s->home_configured?"查看家庭 ›":"待绑定 ›",135,60);
    const char *kinds[]={"temperature","humidity"},*names[]={"室内温度","室内湿度"};
    for(int i=0;i<2;i++){
        int x=i?320:20;PaperOSHomeItem *item=dash_home_metric(a,kinds[i]);
        if(item&&item->room[0])snprintf(b,sizeof(b),"%s · %s",item->room,i?"湿度":"温度");else snprintf(b,sizeof(b),"%s",names[i]);
        dash_fit(x,y+47,23,b,255,50);
        if(item&&item->available)snprintf(b,sizeof(b),"%s %s",item->value,item->unit);
        else snprintf(b,sizeof(b),"— %s",i?"%":"°C");
        dash_fit(x,y+73,40,b,250,item&&item->stale?65:0);
    }
    rect(300,y+47,1,62,190);int states=0;
    for(int i=0;i<a->ui.home.count&&states<3;i++){
        PaperOSHomeItem *item=&a->ui.home.items[i];if(strcmp(item->kind,"state"))continue;
        int x=20+states*190;box(x,y+126,180,48,190);dash_fit(x+8,y+129,19,item->label,163,65);
        dash_fit(x+8,y+151,20,item->available?item->value:"离线",163,item->stale?90:0);states++;
    }
    if(!states)text(20,y+141,19,s->home_configured?(s->home_at?"已连接 · 点此查看室内指标":"等待获取家庭数据"):"在电脑上绑定家庭，选择想看的指标。",550,70);
    if(s->home_at&&time(NULL)-s->home_at>300)text(340,y+17,17,"缓存",80,75);
}
static void dash_mihome(App *a){
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;char b[512];dash_home_data(a);
    dash_header(a,"米家","主页");text(22,135,29,s->home_name[0]?s->home_name:"我的家庭",390,0);
    button(430,127,150,44,s->home_busy?"更新中…":"刷新",false);
    button(20,198,273,46,"室内指标",!u->home_tab);button(307,198,273,46,"设备状态",u->home_tab);
    if(!s->home_configured){
        text(24,315,37,"等待连接家庭",550,0);text(24,392,26,"在电脑完成家庭授权，",550,60);
        text(24,435,26,"选择想在这里查看的室内指标和设备。",550,60);text(24,510,22,"连接后自动更新，断网保留已有读数。",550,75);
    }else{
        int indices[12],count=0,per=u->home_tab?6:4;
        for(int i=0;i<u->home.count;i++)if((!strcmp(u->home.items[i].kind,"state"))==(u->home_tab!=0))indices[count++]=i;
        if(u->home_page*per>=count)u->home_page=count?(count-1)/per:0;
        if(!count){text(24,330,30,s->home_busy?"正在获取家庭数据":"尚未选择这一类显示项",550,0);text(24,392,23,"可在电脑端选择需要显示的设备。",550,65);}
        for(int slot=0;slot<per&&u->home_page*per+slot<count;slot++){
            PaperOSHomeItem *item=&u->home.items[indices[u->home_page*per+slot]];
            if(!u->home_tab){
                int x=20+(slot%2)*287,y=274+(slot/2)*173;box(x,y,273,155,205);
                snprintf(b,sizeof(b),"%s%s%s",item->room,item->room[0]?" · ":"",item->label);dash_fit(x+12,y+12,22,b,249,60);
                snprintf(b,sizeof(b),"%s%s%s",item->available?item->value:"—",item->available&&item->unit[0]?" ":"",item->available?item->unit:"");dash_fit(x+12,y+52,52,b,249,0);
                text(x+12,y+120,17,!item->available?"设备离线":item->stale?"上次读数 · 缓存":"已更新",249,75);
            }else{
                int y=269+slot*60;dash_fit(22,y,26,item->label,370,0);text(22,y+30,17,item->room[0]?item->room:"设备状态",370,75);
                dash_fit(420,y+5,26,item->available?item->value:"离线",160,item->stale?80:0);rect(20,y+53,560,1,210);
            }
        }
        button(20,651,120,44,"上一页",false);button(155,651,120,44,"下一页",false);
        snprintf(b,sizeof(b),"%d / %d",u->home_page+1,count?(count+per-1)/per:1);text(320,660,21,b,260,65);
    }
    if(s->home_at){time_t stamp=s->home_at;struct tm t;localtime_r(&stamp,&t);snprintf(b,sizeof(b),"%02d-%02d %02d:%02d 刷新 · %s",t.tm_mon+1,t.tm_mday,t.tm_hour,t.tm_min,s->home_message);}
    else snprintf(b,sizeof(b),"%s",s->home_message[0]?s->home_message:"尚未获取家庭数据");
    dash_fit(22,706,17,b,555,75);
}

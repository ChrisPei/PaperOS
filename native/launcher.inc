/* Installed apps are launch targets. Catalog entries and package files are not. */
#define DRAWER_PAGE_SIZE 8

static void app_round_box(int x,int y,int side) {
    const int radius=12;
    rect(x+radius,y,side-2*radius,2,0);rect(x+radius,y+side-2,side-2*radius,2,0);
    rect(x,y+radius,2,side-2*radius,0);rect(x+side-2,y+radius,2,side-2*radius,0);
    dash_arc(x+radius,y+radius,radius,180,270,0);
    dash_arc(x+side-radius-2,y+radius,radius,270,360,0);
    dash_arc(x+side-radius-2,y+side-radius-2,radius,0,90,0);
    dash_arc(x+radius,y+side-radius-2,radius,90,180,0);
}

static int app_order(const PaperOSApp *p) {
    const char *ids[]={"org.paperos.koreader","org.paperos.alarm","org.paperos.calendar","org.paperos.weather","org.paperos.mihome","org.paperos.notes","org.paperos.muyu"};
    for(int i=0;i<7;i++)if(!strcmp(p->id,ids[i]))return i;
    return 7;
}

static void drawer_order(App *a,int *order) {
    for(int i=0;i<a->app_count;i++){
        int j=i;order[i]=i;
        while(j>0){PaperOSApp *p=&a->apps[order[j-1]],*q=&a->apps[i];
            int difference=app_order(p)-app_order(q);if(!difference)difference=strcmp(p->name,q->name);
            if(difference<=0)break;
            order[j]=order[j-1];j--;
        }
        order[j]=i;
    }
}

/* One native stroke vocabulary; generic packages also get a readable monogram. */
static void app_glyph(const PaperOSApp *p,int x,int y,bool shop) {
    const char *id=p?p->id:"",*widget=p?p->widget:"";
    if(shop){
        box(x+9,y+21,44,36,0);dash_arc(x+30,y+21,12,180,360,0);
        rect(x+17,y+18,3,13,0);rect(x+41,y+18,3,13,0);
        dash_line(x+20,y+42,x+40,y+42,0);dash_line(x+30,y+32,x+30,y+52,0);
    }else if(!strcmp(id,"org.paperos.koreader")){
        dash_line(x+30,y+14,x+8,y+8,0);dash_line(x+8,y+8,x+8,y+49,0);dash_line(x+8,y+49,x+30,y+55,0);
        dash_line(x+30,y+14,x+52,y+8,0);dash_line(x+52,y+8,x+52,y+49,0);dash_line(x+52,y+49,x+30,y+55,0);dash_line(x+30,y+14,x+30,y+55,0);
        for(int i=0;i<3;i++){dash_line(x+15,y+23+i*8,x+23,y+25+i*8,0);dash_line(x+37,y+25+i*8,x+45,y+23+i*8,0);}
    }else if(!strcmp(widget,"clock")||!strcmp(id,"org.paperos.clock")){
        dash_circle(x+30,y+32,21,0);dash_line(x+30,y+32,x+30,y+17,0);dash_line(x+30,y+32,x+42,y+38,0);
        dash_arc(x+16,y+12,8,200,320,0);dash_arc(x+44,y+12,8,220,340,0);
        dash_line(x+16,y+50,x+11,y+58,0);dash_line(x+44,y+50,x+49,y+58,0);
    }else if(!strcmp(widget,"calendar")){
        box(x+9,y+12,44,44,0);rect(x+9,y+23,44,3,0);rect(x+19,y+6,3,14,0);rect(x+40,y+6,3,14,0);
        for(int r=0;r<2;r++)for(int c=0;c<3;c++)rect(x+18+c*10,y+33+r*11,4,4,0);
    }else if(!strcmp(widget,"weather")){
        dash_circle(x+25,y+24,12,0);
        for(int i=0;i<8;i++){double angle=i*3.141592653589793/4;dash_line(x+25+(int)(cos(angle)*17),y+24+(int)(sin(angle)*17),x+25+(int)(cos(angle)*22),y+24+(int)(sin(angle)*22),0);}
        rect(x+20,y+36,36,15,255);dash_arc(x+32,y+39,11,170,300,0);dash_arc(x+46,y+42,9,235,450,0);dash_line(x+24,y+51,x+48,y+51,0);
    }else if(!strcmp(widget,"mihome")){
        dash_line(x+7,y+29,x+31,y+9,0);dash_line(x+31,y+9,x+55,y+29,0);
        dash_line(x+14,y+25,x+14,y+54,0);dash_line(x+48,y+25,x+48,y+54,0);dash_line(x+14,y+54,x+48,y+54,0);
        box(x+25,y+34,12,20,0);
    }else if(!strcmp(id,"org.paperos.muyu")){
        dash_arc(x+29,y+38,22,155,375,0);dash_line(x+8,y+48,x+49,y+48,0);
        dash_arc(x+30,y+38,9,205,335,0);dash_line(x+38,y+16,x+53,y+5,0);dash_circle(x+37,y+17,4,0);
    }else if(strstr(id,"ace-attorney")||strstr(id,"game")){
        box(x+4,y+22,54,30,0);rect(x+15,y+30,3,15,0);rect(x+9,y+36,15,3,0);
        dash_circle(x+43,y+32,3,0);dash_circle(x+50,y+40,3,0);dash_line(x+22,y+8,x+35,y+8,0);dash_line(x+35,y+8,x+35,y+21,0);
    }else if(!strcmp(id,"org.paperos.notes")){
        box(x+13,y+7,36,49,0);rect(x+10,y+16,8,3,0);rect(x+10,y+28,8,3,0);rect(x+10,y+40,8,3,0);
        for(int i=0;i<3;i++)rect(x+23,y+21+i*10,17,2,0);
    }else{
        char initial[8]={0};const char *end=p->name;codepoint(&end);size_t n=(size_t)(end-p->name);if(n<sizeof(initial))memcpy(initial,p->name,n);
        text(x+(62-text_width(initial,44))/2,y+7,44,initial,62,0);
    }
}

static void app_label(int cx,int y,const char *name,int width) {
    char line[256]={0};const char *p=name;size_t used=0;
    for(int row=0;row<2&&*p;row++){
        used=0;line[0]=0;
        while(*p){const char *end=p;codepoint(&end);size_t n=(size_t)(end-p);if(used+n>=sizeof(line))break;
            memcpy(line+used,p,n);line[used+n]=0;
            if(text_width(line,25)>width){line[used]=0;break;}used+=n;p=end;
        }
        if(row==1&&*p){while(used&&text_width(line,25)+text_width("…",25)>width){do{used--;}while(used&&((unsigned char)line[used]&0xc0)==0x80);line[used]=0;}strcat(line,"…");}
        text(cx-text_width(line,25)/2,y+row*29,25,line,width,0);
    }
}

static void drawer_pages(App *a) {
    int pages=(a->app_count+DRAWER_PAGE_SIZE-1)/DRAWER_PAGE_SIZE;if(!pages)pages=1;
    if(pages<=1)return;
    if(a->drawer_page>0)button(24,665,104,44,"‹ 上页",false);
    if(a->drawer_page+1<pages)button(472,665,104,44,"下页 ›",false);
    for(int i=0;i<pages;i++){int x=300-(pages-1)*12+i*24;dash_circle(x,687,4,0);if(i==a->drawer_page)rect(x-2,685,5,5,0);}
}

static void draw_library(App *a) {
    dash_status(a);text(26,60,40,"应用",400,0);char count[80];snprintf(count,sizeof(count),"%d 个已安装应用",a->app_count);text(26,113,22,count,540,65);
    int order[PAPEROS_MAX_APPS];drawer_order(a,order);
    for(int slot=0;slot<9;slot++){
        bool shop=slot==8;int index=a->drawer_page*DRAWER_PAGE_SIZE+slot;
        if(!shop&&index>=a->app_count)continue;
        PaperOSApp *p=shop?NULL:&a->apps[order[index]];int cx=116+(slot%3)*184,y=169+(slot/3)*163;
        app_round_box(cx-45,y,90);app_glyph(p,cx-31,y+13,shop);app_label(cx,y+101,shop?"应用商店":p->name,170);
        if(shop)text(cx-text_width("发现与下载",18)/2,y+134,18,"发现与下载",170,75);
    }
    if(!a->app_count){text(26,196,29,"这里显示你安装的软件",540,0);text(26,242,23,"打开应用商店，添加第一个应用。",540,65);}
    drawer_pages(a);
    if(a->launch_app>=0&&a->launch_app<a->app_count){char message[192];snprintf(message,sizeof(message),"正在打开 %s…",a->apps[a->launch_app].name);rect(130,664,340,46,255);dash_fit(140,675,22,message,320,0);}
    else if(a->app_message[0]){rect(130,664,340,46,255);dash_fit(140,675,21,a->app_message,320,0);}
}

static void drawer_launch(App *a,int index) {
    if(index<0||index>=a->app_count)return;
    a->launch_app=index;a->app_message[0]=0;
    fprintf(stderr,"PaperOS launch requested: %s\n",a->apps[index].id);
}

static void drawer_swipe(App *a,int x0,int y0,int x1,int y1) {
    if(a->screen!=APP_LIBRARY||a->ui.services.locked||a->ui.services.alert_id[0]||a->ui.services.transfer_id[0]||a->launch_app>=0)return;
    if(y0<150||y0>=660||abs(y1-y0)>140||abs(x1-x0)<100)return;
    if(x1<x0&&(a->drawer_page+1)*DRAWER_PAGE_SIZE<a->app_count){a->drawer_page++;a->dirty=true;}
    if(x1>x0&&a->drawer_page>0){a->drawer_page--;a->dirty=true;}
}

static int manager_rows(App *a,int *rows,int tab) {
    int count=0;
    if(tab==0){int order[PAPEROS_MAX_APPS];drawer_order(a,order);for(int i=0;i<a->app_count;i++)rows[count++]=-order[i]-1;return count;}
    for(int i=0;i<a->store.catalog.count;i++){
        PaperOSStoreEntry *e=&a->store.catalog.entries[i];
        if(!e->installed[0]||(tab==1&&strcmp(e->kind,"koplugin"))||(tab==2&&(!e->update||e->reason[0])))continue;
        if(strcmp(e->kind,"koplugin")&&store_native(a,e->id)<0)continue;
        bool duplicate=false;for(int j=0;j<count;j++)if(!strcmp(a->store.catalog.entries[rows[j]].id,e->id))duplicate=true;
        if(!duplicate)rows[count++]=i;
    }
    return count;
}

static void manager_open(App *a) {
    a->screen=APP_MANAGER;a->show_packages=false;a->confirm_remove=false;a->app_message[0]=0;
    reload_apps(a);dash_command(a,"store-sync",NULL);
}

static void manager_draw(App *a) {
    store_tick(a);dash_header(a,"应用管理","‹ 设置");
    text(30,120,21,"安装、更新与卸载；个人数据会保留",540,65);
    int rows[PAPEROS_STORE_MAX+PAPEROS_MAX_APPS];char labels[3][80];
    snprintf(labels[0],sizeof(labels[0]),"应用 %d",a->app_count);
    snprintf(labels[1],sizeof(labels[1]),"阅读插件 %d",manager_rows(a,rows,1));
    snprintf(labels[2],sizeof(labels[2]),"可更新 %d",manager_rows(a,rows,2));
    for(int i=0;i<3;i++)button(30+183*i,166,174,48,labels[i],a->manager_tab==i);
    int count=manager_rows(a,rows,a->manager_tab);if(a->manager_page*4>=count)a->manager_page=count?(count-1)/4:0;
    for(int r=0;r<4&&a->manager_page*4+r<count;r++){
        int target=rows[a->manager_page*4+r],y=235+r*91;char detail[180];const char *name;
        if(target<0){PaperOSApp *p=&a->apps[-target-1];name=p->name;snprintf(detail,sizeof(detail),"已安装 · %s",p->version);}
        else{PaperOSStoreEntry *e=&a->store.catalog.entries[target];name=e->name;if(a->manager_tab==2)snprintf(detail,sizeof(detail),"%s → %s · %s",e->installed,e->version,store_kind(e));else snprintf(detail,sizeof(detail),"%s · 在 KOReader 内使用",e->installed);}
        dash_fit(34,y+8,28,name,475,0);text(34,y+47,20,detail,496,65);text(548,y+23,30,"›",30,0);rect(30,y+80,540,1,190);
    }
    if(!count){centered(300,29,a->manager_tab==2?"暂未发现可用更新":a->manager_tab==1?"尚未安装阅读器插件":"尚未安装应用");centered(352,21,a->manager_tab==1?"插件安装后，在 KOReader 里使用。":a->manager_tab==2?"联网后可再次检查。":"打开应用商店，发现更多应用。");}
    text(30,592,19,a->app_message[0]?a->app_message:a->ui.message[0]?a->ui.message:"",540,55);
    button(30,609,261,46,"本地应用包",false);button(309,609,261,46,a->ui.services.store_busy?"正在检查…":"检查更新",false);
    button(30,665,110,44,"上页",false);button(460,665,110,44,"下页",false);
    char page[80];snprintf(page,sizeof(page),"%d / %d",a->manager_page+1,count?(count+3)/4:1);text(300-text_width(page,22)/2,676,22,page,220,65);
}

static PaperOSStoreEntry *app_catalog_entry(App *a,const char *id) {
    PaperOSStoreEntry *found=NULL;
    for(int i=0;i<a->store.catalog.count;i++){PaperOSStoreEntry *e=&a->store.catalog.entries[i];if(!strcmp(e->id,id)&&!strcmp(e->kind,"papp")){if(!found||e->update)found=e;}}
    return found;
}

static void packages_draw(App *a) {
    dash_header(a,"本地应用包","‹ 管理");text(30,122,21,"通过 USB 或无线接收的安装包",540,65);
    for(int row=0;row<5&&a->app_page*5+row<a->package_count;row++){
        PaperOSApp *p=&a->packages[a->app_page*5+row];int y=172+row*88;char detail[200];int installed=store_native(a,p->id);
        dash_fit(34,y+7,27,p->name,493,0);snprintf(detail,sizeof(detail),"包版本 %s · %s",p->version,installed>=0?"已安装":"未安装");text(34,y+44,21,detail,510,65);text(550,y+21,28,"›",30,0);rect(30,y+78,540,1,190);
    }
    if(!a->package_count){text(30,230,28,"还没有收到应用包",540,0);text(30,280,22,"在设置中开启「接收应用」，或通过 USB",540,65);text(30,316,22,"放入 paperos/packages 文件夹。",540,65);}
    button(30,665,110,44,"上页",false);button(460,665,110,44,"下页",false);char page[80];snprintf(page,sizeof(page),"%d / %d",a->app_page+1,a->package_count?(a->package_count+4)/5:1);text(300-text_width(page,22)/2,676,22,page,220,65);
}

static void draw_app_details(App *a) {
    store_tick(a);
    int count=a->show_packages?a->package_count:a->app_count;
    if(a->selected_app<0||a->selected_app>=count){a->screen=APP_MANAGER;manager_draw(a);return;}
    PaperOSApp *p=(a->show_packages?a->packages:a->apps)+a->selected_app;
    dash_header(a,a->show_packages?"安装应用":"应用信息",a->show_packages?"‹ 本地包":"‹ 管理");
    app_round_box(30,133,90);app_glyph(p,44,146,false);dash_fit(142,144,32,p->name,428,0);
    char detail[160];snprintf(detail,sizeof(detail),"版本 %s",p->version);text(144,192,22,detail,420,65);
    text(30,250,23,p->description,540,55);text(30,291,18,p->id,540,85);
    int installed=store_native(a,p->id);PaperOSStoreEntry *entry=app_catalog_entry(a,p->id);
    if(a->show_packages){
        if(installed>=0){snprintf(detail,sizeof(detail),"当前已安装 %s",a->apps[installed].version);text(30,350,24,detail,540,0);}else text(30,350,24,"尚未安装",540,0);
        button(30,405,540,58,installed>=0?"安装此版本（保留数据）":"安装应用",true);
        text(30,503,22,"安装完成后，可从「应用」直接打开。",540,65);
        if(a->app_message[0])text(30,551,22,a->app_message,540,0);
    }else{
        text(30,350,24,entry&&entry->update?"有新版本可用":"已安装",540,0);
        button(30,405,540,58,"打开应用",true);
        if(entry){snprintf(detail,sizeof(detail),entry->update?"更新至 %s":"在应用商店查看",entry->version);button(30,481,540,52,detail,false);}
        button(30,557,540,52,a->confirm_remove?"再次点击，确认卸载":"卸载应用",false);
        text(30,631,21,a->confirm_remove?"卸载后入口移除，个人数据仍会保留。":"更新和卸载均保留个人数据。",540,65);
        if(a->app_message[0])text(30,676,20,a->app_message,540,0);
    }
}

static bool launcher_tap(App *a,int x,int y) {
    if(a->screen==APP_MANAGER||a->screen==APP_DETAILS||a->screen==LOCAL_PACKAGES)store_tick(a);
    if(a->screen==APP_LIBRARY){
        if(y>=160&&y<646&&x>=28&&x<572){int col=(x-24)/184,row=(y-160)/163;
            if(col<3&&(x-24)%184<176&&(y-160)%163<153){int slot=row*3+col;
                if(slot==8){a->screen=STORE_HOME;a->store_management=false;a->ui.message[0]=0;dash_command(a,"store-sync",NULL);}
                else{int order[PAPEROS_MAX_APPS];drawer_order(a,order);int index=a->drawer_page*DRAWER_PAGE_SIZE+slot;if(index<a->app_count)drawer_launch(a,order[index]);}
            }
        }else if(y>=665&&y<709){if(x<128&&a->drawer_page>0)a->drawer_page--;else if(x>=472&&(a->drawer_page+1)*DRAWER_PAGE_SIZE<a->app_count)a->drawer_page++;}
        return true;
    }
    if(a->screen==APP_MANAGER){
        if(y>=48&&y<104&&x<160){a->screen=SETTINGS;return true;}
        if(y>=166&&y<214&&x>=30&&x<570){a->manager_tab=(x-30)/183;if(a->manager_tab>2)a->manager_tab=2;a->manager_page=0;a->app_message[0]=0;a->ui.message[0]=0;reload_apps(a);}
        else if(y>=235&&y<599&&(y-235)%91<80&&x>=30&&x<570){int rows[PAPEROS_STORE_MAX+PAPEROS_MAX_APPS],count=manager_rows(a,rows,a->manager_tab),index=a->manager_page*4+(y-235)/91;
            if(index<count){int target=rows[index];a->app_message[0]=0;a->ui.message[0]=0;a->confirm_remove=false;
                if(target<0){a->selected_app=-target-1;a->show_packages=false;a->screen=APP_DETAILS;}
                else{copy_text(a->store.selected,sizeof(a->store.selected),a->store.catalog.entries[target].key);a->store.confirm_remove=false;a->store_management=true;a->store_return=APP_MANAGER;a->screen=STORE_DETAILS;}
            }
        }else if(y>=609&&y<655){if(x>=30&&x<291){a->show_packages=true;a->app_page=0;reload_apps(a);a->screen=LOCAL_PACKAGES;}else if(x>=309&&x<570)dash_command(a,"store-refresh",NULL);}
        else if(y>=665&&y<709){int rows[PAPEROS_STORE_MAX+PAPEROS_MAX_APPS],count=manager_rows(a,rows,a->manager_tab);if(x>=30&&x<140&&a->manager_page>0)a->manager_page--;else if(x>=460&&x<570&&(a->manager_page+1)*4<count)a->manager_page++;}
        return true;
    }
    if(a->screen==LOCAL_PACKAGES){
        if(y>=48&&y<104&&x<160){a->screen=APP_MANAGER;a->show_packages=false;}
        else if(y>=172&&y<612&&(y-172)%88<78&&x>=30&&x<570){int index=a->app_page*5+(y-172)/88;if(index<a->package_count){a->selected_app=index;a->show_packages=true;a->confirm_remove=false;a->app_message[0]=0;a->screen=APP_DETAILS;}}
        else if(y>=665&&y<709){if(x>=30&&x<140&&a->app_page>0)a->app_page--;else if(x>=460&&x<570&&(a->app_page+1)*5<a->package_count)a->app_page++;}
        return true;
    }
    if(a->screen==APP_DETAILS){
        if(y>=48&&y<104&&x<160){a->screen=a->show_packages?LOCAL_PACKAGES:APP_MANAGER;a->confirm_remove=false;return true;}
        int count=a->show_packages?a->package_count:a->app_count;if(a->selected_app<0||a->selected_app>=count)return true;
        PaperOSApp *p=(a->show_packages?a->packages:a->apps)+a->selected_app;
        if(x>=30&&x<570&&y>=405&&y<463){
            if(!a->show_packages)drawer_launch(a,a->selected_app);
            else{char id[64];copy_text(id,sizeof(id),p->id);if(!paperos_app_install(a->app_root,p->directory,a->app_message,sizeof(a->app_message))){a->apps_installed++;a->show_packages=false;reload_apps(a);a->selected_app=store_native(a,id);copy_text(a->app_message,sizeof(a->app_message),"安装完成，应用抽屉已更新。");dash_command(a,"store-sync",NULL);}}
        }else if(!a->show_packages&&x>=30&&x<570&&y>=481&&y<533){PaperOSStoreEntry *entry=app_catalog_entry(a,p->id);if(entry){copy_text(a->store.selected,sizeof(a->store.selected),entry->key);a->store_management=true;a->store_return=APP_DETAILS;a->store.confirm_remove=false;a->ui.message[0]=0;a->screen=STORE_DETAILS;}}
        else if(!a->show_packages&&x>=30&&x<570&&y>=557&&y<609){
            if(!a->confirm_remove)a->confirm_remove=true;
            else if(!paperos_app_remove(a->app_root,p->id,a->app_message,sizeof(a->app_message))){a->apps_removed++;reload_apps(a);a->screen=APP_MANAGER;a->manager_tab=0;a->confirm_remove=false;copy_text(a->app_message,sizeof(a->app_message),"已卸载，个人数据已保留。");dash_command(a,"store-sync",NULL);}
        }return true;
    }
    return false;
}

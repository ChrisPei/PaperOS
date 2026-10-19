/* Wallpaper browsing is read-only until an explicit favorite, mode or use action. */
static const unsigned char *dash_photo_read(const char *path,int *width,int *height) {
    static unsigned char data[W*H];static char cached[800];static int cw,ch;static bool present;
    if(strcmp(cached,path)){
        copy_text(cached,sizeof(cached),path);present=false;cw=ch=0;
        const char *name=strrchr(path,'/');bool safe=name&&strstr(path,"/lockscreen/");
        if(safe){size_t n=strlen(name+1);safe=n==68||n==74;}
        if(safe)for(int i=1;i<=64;i++)if(!((name[i]>='0'&&name[i]<='9')||(name[i]>='a'&&name[i]<='f')))safe=false;
        bool thumb=safe&&!strcmp(name+65,".thumb.pgm");safe=safe&&(thumb||!strcmp(name+65,".pgm"));
        FILE *f=safe?fopen(path,"rb"):NULL;
        if(f){char header[16]={0};cw=thumb?150:W;ch=thumb?200:H;
            const char *expected=thumb?"P5\n150 200\n255\n":"P5\n600 800\n255\n";
            if(fread(header,1,15,f)==15&&!memcmp(header,expected,15)&&fread(data,1,(size_t)cw*ch,f)==(size_t)cw*ch&&fgetc(f)==EOF)present=true;
            fclose(f);
        }
    }
    *width=cw;*height=ch;return present?data:NULL;
}
static bool dash_photo(const char *path,int x,int y,int width,int height) {
    int sw=0,sh=0;const unsigned char *data=NULL;
    if(width<=150&&height<=200&&strlen(path)>4){char thumbnail[800];snprintf(thumbnail,sizeof(thumbnail),"%.*s.thumb.pgm",(int)strlen(path)-4,path);data=dash_photo_read(thumbnail,&sw,&sh);}
    if(!data)data=dash_photo_read(path,&sw,&sh);
    if(!data){rect(x,y,width,height,242);return false;}
    if(x==0&&y==0&&width==W&&height==H&&sw==W&&sh==H){memcpy(pixels,data,sizeof(pixels));return true;}
    for(int dy=0;dy<height;dy++)for(int dx=0;dx<width;dx++){
        int x0=dx*sw/width,y0=dy*sh/height,x1=(dx+1)*sw/width,y1=(dy+1)*sh/height;
        if(x1<=x0)x1=x0+1;
        if(y1<=y0)y1=y0+1;
        int sum=0,count=0;for(int py=y0;py<y1;py++)for(int px=x0;px<x1;px++){sum+=data[py*sw+px];count++;}
        if(x+dx>=0&&x+dx<W&&y+dy>=0&&y+dy<H)pixels[(y+dy)*W+x+dx]=(unsigned char)(sum/count);
    }
    return true;
}
static void dash_gallery_reload(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;
    if(!u->gallery.available||u->gallery.revision!=s->wallpaper_revision)paperos_gallery_read(&u->gallery,s->wallpaper_catalog,s->wallpaper_revision);
    if(!u->wallpaper_selected[0])copy_text(u->wallpaper_selected,sizeof(u->wallpaper_selected),s->wallpaper_current);
}
static int dash_gallery_list(App *a,int *indices) {
    dash_gallery_reload(a);int n=0;for(int i=0;i<a->ui.gallery.count;i++)if(!a->ui.wallpaper_favorites||a->ui.gallery.photos[i].favorite)indices[n++]=i;
    return n;
}
static PaperOSWallpaper *dash_gallery_selected(App *a) {
    dash_gallery_reload(a);for(int i=0;i<a->ui.gallery.count;i++)if(!strcmp(a->ui.gallery.photos[i].id,a->ui.wallpaper_selected))return &a->ui.gallery.photos[i];
    return NULL;
}
static void dash_wallpaper_star(int cx,int cy,bool filled) {
    int x[10],y[10];for(int i=0;i<10;i++){double angle=(-90+i*36)*3.141592653589793/180;int radius=i%2?4:9;x[i]=cx+(int)lround(cos(angle)*radius);y[i]=cy+(int)lround(sin(angle)*radius);}
    if(filled)for(int yy=cy-9;yy<=cy+9;yy++)for(int xx=cx-9;xx<=cx+9;xx++){
        bool inside=false;for(int i=0,j=9;i<10;j=i++)if(((y[i]>yy)!=(y[j]>yy))&&(xx<(x[j]-x[i])*(double)(yy-y[i])/(y[j]-y[i])+x[i]))inside=!inside;
        if(inside)rect(xx,yy,1,1,0);
    }
    for(int i=0;i<10;i++)dash_line(x[i],y[i],x[(i+1)%10],y[(i+1)%10],0);
}
static const char *dash_wallpaper_mode(App *a) {
    if(!strcmp(a->ui.services.wallpaper_mode,"fixed"))return "保持选定图片，不自动更换";
    if(!strcmp(a->ui.services.wallpaper_mode,"favorites"))return "每次锁屏，从收藏中轮换";
    return "按天自动换图，断网使用缓存";
}
static void dash_lock_settings(App *a) {
    PaperOSServices *s=&a->ui.services;char b[160];dash_header(a,"锁屏与壁纸","设置");
    text(22,125,29,"自动锁屏",540,0);
    const char *labels[]={"关闭","1分钟","3分钟","5分钟","10分钟"};int seconds[]={0,60,180,300,600};
    for(int i=0;i<5;i++)button(20+i*114,173,106,46,labels[i],s->idle_seconds==seconds[i]);
    text(22,244,29,"壁纸模式",540,0);
    const char *modes[]={"每日换图","收藏轮换","固定一张"},*values[]={"daily","favorites","fixed"};
    for(int i=0;i<3;i++)button(20+i*190,290,180,46,modes[i],!strcmp(s->wallpaper_mode[0]?s->wallpaper_mode:"daily",values[i]));
    text(22,351,21,dash_wallpaper_mode(a),550,60);
    dash_photo(s->wallpaper_path,22,394,126,168);box(21,393,128,170,185);
    dash_fit(170,394,29,s->wallpaper_title[0]?s->wallpaper_title:"Windows 聚焦",410,0);
    snprintf(b,sizeof(b),"缓存 %d 张 · 收藏 %d 张",s->wallpaper_count,s->wallpaper_favorites);text(170,445,23,b,410,65);
    button(170,508,410,50,"浏览壁纸与收藏",false);
    button(20,575,560,46,"电源与休眠",false);
    button(20,627,273,52,s->wallpaper_busy?"正在缓存…":"更新壁纸",false);button(307,627,273,52,"立即锁屏",true);
    text(22,700,20,a->ui.message[0]?a->ui.message:s->wallpaper_busy?"正在下载，现有图片仍可使用":s->wallpaper_message,550,50);
}
static void dash_wallpapers(App *a) {
    PaperOSDashboard *u=&a->ui;dash_header(a,"壁纸","设置");
    button(20,130,273,46,"全部壁纸",!u->wallpaper_favorites);button(307,130,273,46,"我的收藏",u->wallpaper_favorites);
    int indices[72],n=dash_gallery_list(a,indices),pages=(n+5)/6;if(pages<1)pages=1;if(u->wallpaper_page>=pages)u->wallpaper_page=pages-1;
    for(int cell=0;cell<6&&u->wallpaper_page*6+cell<n;cell++){
        PaperOSWallpaper *p=&u->gallery.photos[indices[u->wallpaper_page*6+cell]];int x=15+(cell%3)*190,y=190+(cell/3)*243;
        dash_photo(p->path,x+15,y,150,200);box(x+14,y-1,152,202,200);
        if(p->favorite){rect(x+136,y+5,25,25,255);dash_wallpaper_star(x+148,y+17,true);}
        if(!strcmp(p->id,u->services.wallpaper_current)){rect(x+85,y+173,80,25,255);text(x+91,y+175,17,"使用中",73,0);}
        dash_fit(x+5,y+208,20,p->title[0]?p->title:"Windows 聚焦",180,0);
    }
    if(!n){centered(334,33,u->wallpaper_favorites?"还没有收藏":"还没有壁纸");centered(390,23,u->wallpaper_favorites?"打开一张图片，点收藏即可保留":"连接 Wi-Fi 后，在设置中更新壁纸");}
    button(20,677,110,42,"上页",false);button(470,677,110,42,"下页",false);
    char b[80];snprintf(b,sizeof(b),"%d / %d · %d张",u->wallpaper_page+1,pages,n);text((W-text_width(b,22))/2,686,22,b,300,55);
}
static void dash_wallpaper_preview(App *a) {
    dash_header(a,"壁纸预览","壁纸");PaperOSWallpaper *p=dash_gallery_selected(a);
    if(!p){centered(295,30,"图片已更新");centered(345,23,"返回壁纸列表重新选择");return;}
    dash_photo(p->path,150,123,300,400);box(149,122,302,402,180);
    button(20,293,70,60,"‹",false);button(510,293,70,60,"›",false);
    text(150,533,18,"点图片查看全屏锁屏效果",350,65);
    dash_fit(22,569,28,p->title,556,0);text(22,607,17,p->credit,556,60);
    button(20,647,273,52,p->favorite?"取消收藏":"收藏这张",p->favorite);button(307,647,273,52,!strcmp(a->ui.services.wallpaper_mode,"fixed")&&!strcmp(p->id,a->ui.services.wallpaper_current)?"当前固定壁纸":"设为壁纸",true);
    if(a->ui.message[0])text(22,704,18,a->ui.message,550,0);
}
static void dash_power(App *a) {
    PaperOSServices *s=&a->ui.services;char b[256];dash_header(a,"电源与休眠","锁屏");
    text(22,138,29,"电池供电时自动休眠",410,0);button(450,137,130,46,s->sleep_enabled?"已开启":"已关闭",s->sleep_enabled);
    text(22,194,21,"锁屏后 15 秒进入，短按电源键唤醒。",550,60);
    text(22,249,27,"接电时延长自动锁屏",550,0);
    const char *labels[]={"2 倍","3 倍","5 倍","10 倍"};int times[]={2,3,5,10};
    int selected=s->powered_multiplier?s->powered_multiplier:5;
    for(int i=0;i<4;i++)button(20+i*143,296,131,46,labels[i],selected==times[i]);
    if(s->idle_seconds>0)snprintf(b,sizeof(b),"电池 %d 分钟 · 接电 %d 分钟",s->idle_seconds/60,s->idle_seconds*selected/60);
    else copy_text(b,sizeof(b),"自动锁屏已关闭，仍可用电源键锁屏。");
    text(22,359,21,b,550,60);
    text(22,405,22,"当前状态",550,65);text(22,441,25,a->ui.message[0]?a->ui.message:s->sleep_message,550,0);
    text(22,492,22,"上次休眠",550,65);
    if(s->sleep_seconds>0){snprintf(b,sizeof(b),"%.0f 秒 · %s",s->sleep_seconds,!strcmp(s->sleep_wake,"rtc")?"定时唤醒":"电源键或 USB 唤醒");text(22,527,25,b,550,0);}else text(22,527,25,"尚无休眠记录",550,0);
    text(22,577,21,"接电时始终保持唤醒，充满电也一样。",550,60);
    text(22,610,21,"拔电后恢复原来的锁屏和休眠设置。",550,60);
    button(20,644,560,48,s->external_power?"接电时不休眠":"立即休眠",!s->external_power);
    text(22,703,17,"短按电源键始终可以锁屏、解锁。",550,75);
}
static void dash_lock_content(App *a,const char *path,const char *title,const char *credit,bool preview) {
    if(!dash_photo(path,0,0,W,H))for(int y=0;y<H;y++)rect(0,y,W,1,(unsigned char)(250-y*35/H));
    for(int y=0;y<H;y++){
        int alpha=y<250?225-y*50/250:y<340?(340-y)*175/90:y>500?(y-500)*244/240:0;if(alpha>244)alpha=244;
        if(alpha)for(int x=0;x<W;x++)pixels[y*W+x]=(unsigned char)((pixels[y*W+x]*(255-alpha)+255*alpha)/255);
    }
    bool sleeping=!preview&&!strcmp(a->ui.services.sleep_phase,"preparing");
    text(28,17,21,sleeping?"PAPEROS · 休眠时刻":"PAPEROS",520,0);
    struct tm local;dash_local(&local);char b[256];strftime(b,sizeof(b),"%H:%M",&local);text(24,46,126,b,550,0);
    snprintf(b,sizeof(b),"%d月%d日  %s",local.tm_mon+1,local.tm_mday,week_names[(local.tm_wday+6)%7]);text(30,174,29,b,540,0);
    paperos_lunar_label(local.tm_year+1900,local.tm_mon+1,local.tm_mday,true,b,sizeof(b));text(31,215,21,b,540,25);
    dash_fit(27,628,30,title[0]?title:"留一点时间给自己",546,0);text(28,669,17,credit[0]?credit:"Windows 聚焦 · 联网后自动下载",545,25);
    if(!preview){dash_line(287,735,300,722,0);dash_line(300,722,313,735,0);}
    centered(753,24,preview?"预览 · 点按任意处返回":sleeping?"短按电源键唤醒":"短按电源键 / 向上滑动解锁");
}
static void dash_lock(App *a) {
    PaperOSServices *s=&a->ui.services;dash_lock_content(a,s->wallpaper_path,s->wallpaper_title,s->wallpaper_credit,false);
}
static void dash_wallpaper_fullscreen(App *a) {
    PaperOSWallpaper *p=dash_gallery_selected(a);if(!p){a->screen=WALLPAPERS;dash_wallpapers(a);return;}
    dash_lock_content(a,p->path,p->title,p->credit,true);
}
static void dash_wallpaper_move(App *a,int direction) {
    int indices[72],n=dash_gallery_list(a,indices),current=0;
    for(int i=0;i<n;i++)if(!strcmp(a->ui.gallery.photos[indices[i]].id,a->ui.wallpaper_selected))current=i;
    if(n){current=(current+direction+n)%n;copy_text(a->ui.wallpaper_selected,sizeof(a->ui.wallpaper_selected),a->ui.gallery.photos[indices[current]].id);a->ui.message[0]=0;a->ui.display_transition=true;}
}
static bool dash_wallpaper_tap(App *a,int x,int y) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;char b[32];
    if(a->screen==LOCK_SETTINGS){
        if(y>=173&&y<219){int choices[]={0,60,180,300,600};int col=(x-20)/114;if(x>=20&&col<5){snprintf(b,sizeof(b),"%d",choices[col]);const char *args[]={"seconds",b,NULL};dash_command(a,"lock-idle",args);}}
        else if(y>=290&&y<336){int col=(x-20)/190;const char *modes[]={"daily","favorites","fixed"};if(x>=20&&col<3){const char *args[]={"mode",modes[col],NULL};dash_command(a,"wallpaper-mode",args);}}
        else if(y>=387&&y<568){a->screen=WALLPAPERS;u->wallpaper_page=0;u->wallpaper_favorites=false;u->message[0]=0;}
        else if(y>=575&&y<621){a->screen=POWER_SETTINGS;u->message[0]=0;}
        else if(y>=627&&y<679){if(x>=307)dash_command(a,"lock-now",NULL);else if(x<293&&!s->wallpaper_busy)dash_command(a,"wallpaper-refresh",NULL);}
        return true;
    }
    if(a->screen==WALLPAPERS){
        int indices[72],n=dash_gallery_list(a,indices);
        if(y>=130&&y<176){u->wallpaper_favorites=x>=300;u->wallpaper_page=0;return true;}
        if(y>=677&&y<719){if(x<140&&u->wallpaper_page>0)u->wallpaper_page--;if(x>=470&&(u->wallpaper_page+1)*6<n)u->wallpaper_page++;return true;}
        int row=(y-190)/243,col=(x-15)/190,index=u->wallpaper_page*6+row*3+col;
        if(x>=15&&x<585&&y>=190&&y<671&&row<2&&col<3&&index<n){copy_text(u->wallpaper_selected,sizeof(u->wallpaper_selected),u->gallery.photos[indices[index]].id);u->message[0]=0;a->screen=WALLPAPER_PREVIEW;u->display_transition=true;}
        return true;
    }
    if(a->screen==WALLPAPER_PREVIEW){
        if(y>=293&&y<353&&(x<100||x>=500)){dash_wallpaper_move(a,x<100?-1:1);return true;}
        if(x>=150&&x<450&&y>=123&&y<552){a->screen=WALLPAPER_FULLSCREEN;u->display_transition=true;return true;}
        PaperOSWallpaper *p=dash_gallery_selected(a);if(p&&y>=647&&y<699){
            PaperOSWallpaper selected=*p;const char *args[]={"id",selected.id,"enabled",selected.favorite?"false":"true",NULL};
            if(dash_command(a,x<300?"wallpaper-favorite":"wallpaper-use",args)){
                copy_text(u->message,sizeof(u->message),s->message);
                if(x<300&&selected.favorite&&!selected.cached&&!selected.fixed)a->screen=WALLPAPERS;
                dash_gallery_reload(a);
            }
        }return true;
    }
    return false;
}

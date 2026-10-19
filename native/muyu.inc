/* Offline wooden fish; app data survives exit, restart and reinstallation. */
static double muyu_now(void) {
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;
}
static void muyu_day(char day[11]) {
    time_t now=time(NULL);struct tm local;localtime_r(&now,&local);strftime(day,11,"%Y-%m-%d",&local);
}
static void muyu_roll_day(PaperOSMuyu *m) {
    char today[11];muyu_day(today);
    if(strcmp(m->day,today)){copy_text(m->day,sizeof(m->day),today);m->today=0;}
}
static void muyu_init(App *a) {
    PaperOSMuyu *m=&a->muyu;m->valid=true;
    if(!m->path[0]){
        const char *data=getenv("PAPEROS_DATA_DIR");
        if(data&&*data){
            if(snprintf(m->path,sizeof(m->path),"%s/merit.state",data)>=(int)sizeof(m->path))m->valid=false;
        }else if(!a->ui.preview){m->valid=false;copy_text(m->message,sizeof(m->message),"请从应用列表打开木鱼");}
    }
    if(m->path[0]){
        FILE *f=fopen(m->path,"r");
        if(f){
            char buffer[192]={0},total[21]={0},daily[21]={0},day[11]={0},extra;
            size_t n=fread(buffer,1,sizeof(buffer)-1,f);bool okay=!ferror(f)&&fgetc(f)==EOF;fclose(f);
            okay=okay&&n>0&&sscanf(buffer,"paperos-muyu-v1 %20[0-9] %20[0-9] %10[0-9-] %c",total,daily,day,&extra)==3;
            if(okay){
                errno=0;m->total=strtoull(total,NULL,10);okay=errno==0;
                errno=0;m->today=strtoull(daily,NULL,10);okay=okay&&errno==0&&m->today<=m->total;
                okay=okay&&strlen(day)==10&&day[4]=='-'&&day[7]=='-';
                copy_text(m->day,sizeof(m->day),day);
            }
            if(!okay){m->valid=false;copy_text(m->message,sizeof(m->message),"计数文件异常，原文件已保留");}
        }else if(errno!=ENOENT){m->valid=false;copy_text(m->message,sizeof(m->message),"无法读取计数，请重新打开");}
    }
    muyu_roll_day(m);
}
static bool muyu_save(PaperOSMuyu *m,unsigned long long total,unsigned long long today) {
    if(!m->path[0])return true; /* Static previews without app data never write. */
    char temporary[800];snprintf(temporary,sizeof(temporary),"%s.tmp.XXXXXX",m->path);
    int fd=mkstemp(temporary);if(fd<0)return false;
    char record[128];int length=snprintf(record,sizeof(record),"paperos-muyu-v1\n%llu %llu %s\n",total,today,m->day);
    size_t pos=0;bool okay=true;
    while(pos<(size_t)length){ssize_t n=write(fd,record+pos,(size_t)length-pos);if(n<0&&errno==EINTR)continue;if(n<=0){okay=false;break;}pos+=(size_t)n;}
    if(okay&&fsync(fd))okay=false;
    if(close(fd))okay=false;
    if(okay&&rename(temporary,m->path))okay=false;
    if(!okay)unlink(temporary);
    return okay;
}
static void muyu_hit(App *a,int x,int y) {
    PaperOSMuyu *m=&a->muyu;
    if(y>=48&&y<105&&x<180){a->return_requested=true;return;}
    if(x<50||x>=550||y<330||y>=630)return;
    if(!m->valid){a->dirty=true;return;}
    muyu_roll_day(m);
    if(m->total==~0ULL||m->today==~0ULL){copy_text(m->message,sizeof(m->message),"功德已圆满");a->dirty=true;return;}
    if(!muyu_save(m,m->total+1,m->today+1)){copy_text(m->message,sizeof(m->message),"保存失败，本次未计入，请重试");a->dirty=true;return;}
    m->total++;m->today++;m->session++;m->message[0]=0;m->feedback_until=muyu_now()+0.65;a->dirty=true;
}
static void muyu_ellipse(int cx,int cy,int rx,int ry,unsigned char ink) {
    for(int y=cy-ry;y<=cy+ry;y++){
        double relative=(double)(y-cy)/ry;
        int half=(int)(rx*sqrt(fmax(0,1-relative*relative)));
        rect(cx-half,y,half*2+1,1,ink);
    }
}
static void muyu_stick(int x0,int y0,int x1,int y1) {
    int steps=abs(x1-x0)>abs(y1-y0)?abs(x1-x0):abs(y1-y0);
    for(int i=0;i<=steps;i++){int x=x0+(x1-x0)*i/steps,y=y0+(y1-y0)*i/steps;rect(x-6,y-6,13,13,0);rect(x-2,y-3,4,6,185);}
}
static void muyu_draw(App *a) {
    PaperOSMuyu *m=&a->muyu;muyu_roll_day(m);bool hit=m->feedback_until>muyu_now();
    dash_header(a,"木鱼","主页");
    centered(140,24,"累计功德");
    char counter[64];snprintf(counter,sizeof(counter),"%llu",m->total);
    int size=88;while(size>24&&text_width(counter,size)>540)size-=2;
    centered(176,size,m->valid?counter:"—");
    centered(292,hit?35:24,hit?"功德 +1":"一敲一念，心自清静");
    int drop=hit?7:0;
    /* Carved body, grain and the characteristic open mouth. */
    muyu_ellipse(300,550,188,13,220);
    muyu_ellipse(292,479+drop,184,95,0);
    muyu_ellipse(292,472+drop,174,84,195);
    muyu_ellipse(286,456+drop,150,62,90);
    muyu_ellipse(286,451+drop,145,57,200);
    muyu_ellipse(277,438+drop,118,39,125);
    muyu_ellipse(277,434+drop,114,35,207);
    for(int i=0;i<85;i++)rect(302+i,466+i/5+drop,4,16+i/9,0);
    muyu_ellipse(417,475+drop,28,28,0);
    muyu_ellipse(417,469+drop,16,14,255);
    muyu_ellipse(371,434+drop,7,7,0);
    /* A small mallet changes position for the impact frame. */
    int mx=hit?312:337,my=hit?393:363;
    muyu_stick(mx+13,my-4,478,hit?352:309);
    muyu_ellipse(mx,my,34,25,0);muyu_ellipse(mx-5,my-5,25,16,225);
    rect(40,624,520,1,190);
    char today[80],session[80];snprintf(today,sizeof(today),"今日  %llu",m->today);snprintf(session,sizeof(session),"本次  %llu",m->session);
    text(45,647,27,today,250,0);text(330,647,27,session,240,0);
    centered(692,21,m->message[0]?m->message:"轻敲木鱼 · 次次自动保存");
}

static void battery_duration(char *out,size_t size,double seconds) {
    long minutes=(long)(seconds/60.0);
    if(minutes<1)snprintf(out,size,"不足1分钟");
    else if(minutes<60)snprintf(out,size,"%ld分钟",minutes);
    else snprintf(out,size,"%ld小时%02ld分",minutes/60,minutes%60);
}
static void dash_battery_page(App *a) {
    PaperOSServices *s=&a->ui.services;PaperOSBatteryHistory *h=&a->ui.battery;char b[256],duration[80];
    dash_header(a,"电量与续航","设置");
    if(!s->battery_available){text(22,148,38,"正在读取电池",550,0);text(22,222,25,"采样可用后开始记录续航。",550,65);return;}
    if(!h->available||h->revision!=s->battery_revision){if(!paperos_battery_read(h,s->battery_history,s->battery_revision))memset(h,0,sizeof(*h));}
    snprintf(b,sizeof(b),"%d%%",s->battery_percent);text(20,120,88,b,315,0);
    text(350,140,27,s->battery_powered?(!strcmp(s->battery_status,"Full")?"已接电 · 已充满":"已接电"):"使用电池",230,0);
    text(350,184,19,"数据从安装本版后积累",230,65);
    button(20,239,273,46,"近24小时",!a->ui.battery_tab);button(307,239,273,46,"最近7天",a->ui.battery_tab);
    if(!a->ui.battery_tab){
        if(h->observed>=60){battery_duration(duration,sizeof(duration),h->observed);snprintf(b,sizeof(b),"掉电 %d 个百分点 · 有效观测 %s",h->drop,duration);}
        else snprintf(b,sizeof(b),"正在积累记录，尚不足以统计掉电。");
        text(22,304,21,b,550,50);
        int left=62,top=355,width=492,height=174;
        for(int level=0;level<=100;level+=50){int y=top+height-level*height/100;rect(left,y,width,1,205);snprintf(b,sizeof(b),"%d",level);text(20,y-11,17,b,40,75);}
        for(int i=0;i<h->point_count;i++){
            PaperOSBatteryPoint *p=&h->points[i];
            if(h->to<=h->from)continue;
            int x=left+(int)((double)(p->at-h->from)*width/(h->to-h->from)),y=top+height-p->percent*height/100;
            if(x<left||x>left+width)continue;
            if(i>0&&p->connected){PaperOSBatteryPoint *old=&h->points[i-1];int px=left+(int)((double)(old->at-h->from)*width/(h->to-h->from)),py=top+height-old->percent*height/100;dash_line(px,py,x,y,0);}
            if(p->powered)box(x-3,y-3,6,6,0);else rect(x-2,y-2,4,4,0);
        }
        text(57,541,18,"24小时前",150,65);text(271,541,18,"12小时前",150,65);text(517,541,18,"现在",65,65);
        if(h->point_count<2)text(145,414,25,"继续使用后显示电量曲线",400,75);
        text(22,592,21,"实际休眠",270,65);text(320,592,21,"唤醒次数",260,65);
        battery_duration(duration,sizeof(duration),h->sleeping);text(22,623,31,duration,280,0);snprintf(b,sizeof(b),"%d 次",h->rtc+h->power+h->other);text(320,623,31,b,260,0);
        snprintf(b,sizeof(b),"定时 %d · 电源键/USB %d · 失败 %d",h->rtc,h->power,h->failures);text(22,670,18,b,550,60);
    }else{
        text(22,307,20,"日期",155,65);text(182,307,20,"掉电",100,65);text(295,307,20,"休眠",190,65);text(504,307,20,"唤醒",80,65);
        for(int i=0;i<h->day_count;i++){
            PaperOSBatteryDay *d=&h->days[i];int y=347+i*47;
            text(22,y,24,strlen(d->date)>5?d->date+5:d->date,150,0);
            if(d->observed>=60){snprintf(b,sizeof(b),"%d%%",d->drop);text(182,y,24,b,100,0);battery_duration(duration,sizeof(duration),d->sleeping);text(295,y+2,20,duration,195,0);}else{text(182,y,24,"—",100,70);text(295,y,24,"—",190,70);}
            snprintf(b,sizeof(b),"%d",d->wakes);text(520,y,24,b,60,0);rect(20,y+39,560,1,220);
        }
    }
    text(22,706,16,s->battery_message[0]?s->battery_message:"充电区间不计掉电，断档不连线；不额外唤醒设备采样。",555,75);
}

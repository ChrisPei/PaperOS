#include "calendar.h"
#include <stdio.h>
#include <string.h>
#include "lunar-data.h"
#include "solar-terms-data.h"
static bool leap_year(int y) { return y%4==0 && (y%100!=0 || y%400==0); }
int paperos_month_days(int y,int m) {
    static const int days[]={31,28,31,30,31,30,31,31,30,31,30,31};
    if(m<1 || m>12) return 0;
    return days[m-1]+(m==2 && leap_year(y));
}
static int ordinal(int y,int m,int d) {
    int days=-25567;
    for(int i=1900;i<y;i++) days+=365+leap_year(i);
    for(int i=1;i<m;i++) days+=paperos_month_days(y,i);
    return days+d-1;
}
int paperos_weekday(int y,int m,int d) { int n=(ordinal(y,m,d)+3)%7; return n<0?n+7:n; }
bool paperos_lunar(int y,int m,int d,int *ly,int *lm,int *ld,bool *leap) {
    if(y<1901 || y>2100 || m<1 || m>12 || d<1 || d>paperos_month_days(y,m)) return false;
    int target=ordinal(y,m,d),lo=0,hi=(int)(sizeof(lunar_months)/sizeof(lunar_months[0]))-1;
    while(lo<hi) { int mid=(lo+hi+1)/2; if(lunar_months[mid].day<=target) lo=mid; else hi=mid-1; }
    int day=target-lunar_months[lo].day+1; if(day<1 || day>30) return false;
    *ly=lunar_months[lo].year; *lm=lunar_months[lo].month; *ld=day; *leap=lunar_months[lo].leap!=0; return true;
}
void paperos_lunar_label(int y,int m,int d,bool full,char *out,size_t size) {
    static const char *months[]={"正月","二月","三月","四月","五月","六月","七月","八月","九月","十月","冬月","腊月"};
    static const char *days[]={"初一","初二","初三","初四","初五","初六","初七","初八","初九","初十","十一","十二","十三","十四","十五","十六","十七","十八","十九","二十","廿一","廿二","廿三","廿四","廿五","廿六","廿七","廿八","廿九","三十"};
    static const char *stems[]={"甲","乙","丙","丁","戊","己","庚","辛","壬","癸"},*branches[]={"子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"};
    int ly,lm,ld; bool leap;
    if(!paperos_lunar(y,m,d,&ly,&lm,&ld,&leap)) { snprintf(out,size,"%s",full?"农历支持1901—2100年":""); return; }
    if(full) snprintf(out,size,"%s%s年 %s%s%s",stems[(ly-4)%10],branches[(ly-4)%12],leap?"闰":"",months[lm-1],days[ld-1]);
    else snprintf(out,size,"%s%s",ld==1&&leap?"闰":"",ld==1?months[lm-1]:days[ld-1]);
}
static const char *solar_names[]={
    "小寒","大寒","立春","雨水","惊蛰","春分","清明","谷雨","立夏","小满","芒种","夏至",
    "小暑","大暑","立秋","处暑","白露","秋分","寒露","霜降","立冬","小雪","大雪","冬至"
};
static bool valid_date(int y,int m,int d) {
    return y>=1901&&y<=2100&&m>=1&&m<=12&&d>=1&&d<=paperos_month_days(y,m);
}
const char *paperos_solar_term(int y,int m,int d) {
    if(!valid_date(y,m,d))return "";
    for(int i=(m-1)*2;i<m*2;i++)if(solar_term_days[y-1901][i]==d)return solar_names[i];
    return "";
}
const char *paperos_next_solar_term(int y,int m,int d,int *ny,int *nm,int *nd,int *until) {
    if(!valid_date(y,m,d))return "";
    int today=ordinal(y,m,d);
    for(int year=y;year<=y+1&&year<=2100;year++)for(int i=0;i<24;i++){
        int month=i/2+1,day=solar_term_days[year-1901][i],delta=ordinal(year,month,day)-today;
        if(delta>0){if(ny)*ny=year;if(nm)*nm=month;if(nd)*nd=day;if(until)*until=delta;return solar_names[i];}
    }
    return "";
}
static void append_event(char *out,size_t size,const char *label) {
    if(!size||!label[0])return;
    size_t used=strlen(out);const char *separator=used?" · ":"";
    if(used+strlen(separator)+strlen(label)<size)snprintf(out+used,size-used,"%s%s",separator,label);
}
void paperos_festival_label(int y,int m,int d,char *out,size_t size) {
    static const struct { int month,day;const char *name; } civil[]={
        {1,1,"元旦"},{2,14,"情人节"},{3,8,"妇女节"},{3,12,"植树节"},{5,1,"劳动节"},
        {5,4,"青年节"},{6,1,"儿童节"},{7,1,"建党节"},{8,1,"建军节"},{9,10,"教师节"},
        {10,1,"国庆节"},{12,24,"平安夜"},{12,25,"圣诞节"}
    },lunar[]={
        {1,1,"春节"},{1,15,"元宵节"},{2,2,"龙抬头"},{5,5,"端午节"},{7,7,"七夕"},
        {7,15,"中元节"},{8,15,"中秋节"},{9,9,"重阳节"},{12,8,"腊八节"},{12,23,"北方小年"},{12,24,"南方小年"}
    };
    if(!size)return;
    out[0]=0;if(!valid_date(y,m,d))return;
    for(size_t i=0;i<sizeof(civil)/sizeof(civil[0]);i++)if(civil[i].month==m&&civil[i].day==d)append_event(out,size,civil[i].name);
    if(m==5&&d>=8&&d<=14&&paperos_weekday(y,m,d)==6)append_event(out,size,"母亲节");
    if(m==6&&d>=15&&d<=21&&paperos_weekday(y,m,d)==6)append_event(out,size,"父亲节");
    int ly,lm,ld;bool leap;
    if(paperos_lunar(y,m,d,&ly,&lm,&ld,&leap)&&!leap){
        for(size_t i=0;i<sizeof(lunar)/sizeof(lunar[0]);i++)if(lunar[i].month==lm&&lunar[i].day==ld)append_event(out,size,lunar[i].name);
        if(lm==12&&ld>=29){
            int year=y,month=m,day=d+1;
            if(day>paperos_month_days(year,month)){day=1;month++;if(month>12){month=1;year++;}}
            if(paperos_lunar(year,month,day,&ly,&lm,&ld,&leap)&&!leap&&lm==1&&ld==1)append_event(out,size,"除夕");
        }
    }
}
void paperos_calendar_events(int y,int m,int d,char *out,size_t size) {
    paperos_festival_label(y,m,d,out,size);
    append_event(out,size,paperos_solar_term(y,m,d));
}

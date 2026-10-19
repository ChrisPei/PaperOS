/* Location settings use the shared keyboard; network searches run in the service. */
static void dash_begin_weather_location(App *a) {
    PaperOSDashboard *u=&a->ui;u->weather_location_page=0;u->message[0]=0;
    copy_text(u->weather_query,sizeof(u->weather_query),u->services.location_query);a->screen=WEATHER_LOCATION;
}
static void dash_weather_search(App *a) {
    PaperOSDashboard *u=&a->ui;
    if(!u->weather_query[0]){u->input_task=3;return;}
    u->weather_location_page=0;
    const char *args[]={"query",u->weather_query,NULL};
    if(dash_command(a,"weather-search",args))copy_text(u->weather_query,sizeof(u->weather_query),u->services.location_query);
}
static void dash_weather_location(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;dash_header(a,"天气地区","天气");
    text(22,125,22,"当前地区",390,65);dash_fit(22,160,30,s->weather_name,390,0);
    button(430,137,150,48,"手动设置",false);
    box(20,216,438,54,0);dash_fit(35,230,25,u->weather_query[0]?u->weather_query:"输入城市或区县名称…",408,u->weather_query[0]?0:95);
    button(473,216,107,54,"搜索",true);
    bool matching=!strcmp(u->weather_query,s->location_query);
    const char *message=u->message[0]?u->message:matching&&s->location_message[0]?s->location_message:"搜索国内城市或区县；同名地点请核对省市";
    text(22,288,21,message,556,55);
    int n=matching?s->place_count:0,pages=(n+3)/4;if(pages<1)pages=1;if(u->weather_location_page>=pages)u->weather_location_page=pages-1;
    for(int row=0;row<4&&u->weather_location_page*4+row<n;row++){
        PaperOSPlace *p=&s->places[u->weather_location_page*4+row];int y=329+row*78;
        dash_fit(22,y,29,p->name,510,0);text(22,y+36,20,p->area,520,65);text(551,y+12,31,"›",32,0);rect(20,y+69,560,1,205);
    }
    if(n){char b[48];button(20,660,110,46,"上页",false);button(470,660,110,46,"下页",false);snprintf(b,sizeof(b),"%d / %d · %d个地区",u->weather_location_page+1,pages,n);text((W-text_width(b,22))/2,672,22,b,310,60);}
    else if(!s->location_busy){text(22,400,25,"找不到所需地区？",550,0);text(22,449,22,"可去掉市、区等后缀，或按省市限定搜索。",550,60);text(22,493,22,"也可以点右上角手动设置经纬度。",550,60);}
    text(22,709,16,"地区搜索：Open-Meteo / GeoNames",550,85);
}
static void dash_begin_weather_coordinates(App *a) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;
    copy_text(u->weather_edit_name,sizeof(u->weather_edit_name),s->weather_name);
    snprintf(u->weather_edit_latitude,sizeof(u->weather_edit_latitude),"%.6f",s->weather_latitude);
    snprintf(u->weather_edit_longitude,sizeof(u->weather_edit_longitude),"%.6f",s->weather_longitude);
    u->message[0]=0;a->screen=WEATHER_COORDINATES;
}
static void dash_weather_coordinates(App *a) {
    PaperOSDashboard *u=&a->ui;dash_header(a,"手动设置地区","地区");
    const char *labels[]={"地区名称","纬度（-90 至 90）","经度（-180 至 180）"};
    const char *values[]={u->weather_edit_name,u->weather_edit_latitude,u->weather_edit_longitude};
    for(int i=0;i<3;i++){int y=132+i*125;text(22,y,25,labels[i],550,60);box(20,y+41,560,54,0);dash_fit(35,y+54,28,values[i],530,0);}
    text(22,537,23,"填写地图上的 WGS84 经纬度，点保存生效。",550,65);
    if(u->message[0])text(22,584,21,u->message,550,0);
    button(20,647,273,52,"恢复北京朝阳",false);button(307,647,273,52,"保存地区",true);
}
static bool dash_weather_location_tap(App *a,int x,int y) {
    PaperOSDashboard *u=&a->ui;PaperOSServices *s=&u->services;
    if(a->screen==WEATHER_LOCATION){
        if(x>=430&&y>=137&&y<185){dash_begin_weather_coordinates(a);return true;}
        if(y>=216&&y<270){if(x<463)u->input_task=3;else dash_weather_search(a);return true;}
        if(y>=329&&y<641&&!strcmp(u->weather_query,s->location_query)){
            int index=u->weather_location_page*4+(y-329)/78;
            if(index<s->place_count){PaperOSPlace selected=s->places[index];const char *args[]={"key",selected.key,NULL};if(dash_command(a,"weather-location-select",args)){u->weather_page=0;a->screen=WEATHER;}}
        }
        if(y>=660&&y<706){if(x<140&&u->weather_location_page>0)u->weather_location_page--;if(x>=470&&(u->weather_location_page+1)*4<s->place_count)u->weather_location_page++;}
        return true;
    }
    if(a->screen==WEATHER_COORDINATES){
        for(int i=0;i<3;i++){int top=173+i*125;if(y>=top&&y<top+54){u->input_task=4+i;return true;}}
        if(y>=647&&y<699){
            const char *args[]={"name",u->weather_edit_name,"latitude",u->weather_edit_latitude,"longitude",u->weather_edit_longitude,NULL};
            if(dash_command(a,x<300?"weather-location-default":"weather-location-set",x<300?NULL:args)){u->weather_page=0;a->screen=WEATHER;}
        }return true;
    }
    return false;
}
static void dash_weather_input(App *a,int task) {
    PaperOSDashboard *u=&a->ui;char *value=NULL;size_t capacity=0;unsigned flags=0;
    const char *title="搜索天气地区";
    if(task==3){value=u->weather_query;capacity=sizeof(u->weather_query);}
    if(task==4){value=u->weather_edit_name;capacity=sizeof(u->weather_edit_name);title="地区名称";}
    if(task==5){value=u->weather_edit_latitude;capacity=sizeof(u->weather_edit_latitude);title="纬度：-90 至 90";flags=PAPEROS_INPUT_ENGLISH;}
    if(task==6){value=u->weather_edit_longitude;capacity=sizeof(u->weather_edit_longitude);title="经度：-180 至 180";flags=PAPEROS_INPUT_ENGLISH;}
    if(!value)return;
    int status=paperos_input_text(title,value,flags,value,capacity);
    if(status==PAPEROS_INPUT_ACCEPTED){u->message[0]=0;if(task==3)dash_weather_search(a);}
    else if(status!=PAPEROS_INPUT_CANCELLED)copy_text(u->message,sizeof(u->message),"系统输入法暂不可用");
}

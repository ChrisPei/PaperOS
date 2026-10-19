/* Native launcher store: the service downloads; a local tap approves installation. */
static void store_tick(App *a){
    if(a->screen!=APP_LIBRARY&&a->screen!=STORE_DETAILS&&a->screen!=STORE_SOURCES&&a->screen!=STORE_COMMUNITY)return;
    PaperOSServices *s=&a->ui.services;
    if(s->store_revision&&s->store_revision!=a->store.catalog.revision&&paperos_store_read(&a->store.catalog,s->store_catalog,s->store_revision)){
        reload_apps(a);a->dirty=true;
    }
}
static PaperOSStoreEntry *store_selected(App *a){
    for(int i=0;i<a->store.catalog.count;i++)if(!strcmp(a->store.selected,a->store.catalog.entries[i].key))return &a->store.catalog.entries[i];
    return NULL;
}
static int store_native(App *a,const char *id){for(int i=0;i<a->app_count;i++)if(!strcmp(id,a->apps[i].id))return i;return -1;}
static bool store_contains(const char *text,const char *query){
    if(!*query)return true;
    for(;*text;text++){const unsigned char *p=(const unsigned char*)text,*q=(const unsigned char*)query;while(*p&&*q){unsigned a=*p,b=*q;if(a>='A'&&a<='Z')a+=32;if(b>='A'&&b<='Z')b+=32;if(a!=b)break;p++;q++;}if(!*q)return true;}
    return false;
}
static bool store_matches(App *a,const char *name,const char *description){return store_contains(name,a->store.query)||store_contains(description,a->store.query);}
static const char *store_kind(const PaperOSStoreEntry *e){
    if(!strcmp(e->kind,"koplugin"))return "阅读器插件";
    if(!strcmp(e->kind,"papp"))return "PaperOS 应用";
    if(!strcmp(e->kind,"font"))return "字体包";
    if(!strcmp(e->kind,"kopatch"))return "用户补丁";
    if(!strcmp(e->kind,"iconpack"))return "图标包";
    return "社区应用";
}
static const char *store_filter_name(App *a){
    for(int i=0;i<a->store.catalog.source_count;i++)if(a->store.catalog.sources[i].enabled&&!strcmp(a->store.filter_source,a->store.catalog.sources[i].id))return a->store.catalog.sources[i].name;
    a->store.filter_source[0]=0;return "全部应用源";
}
static void store_filter_next(App *a){
    int next=0;if(a->store.filter_source[0])for(int i=0;i<a->store.catalog.source_count;i++)if(!strcmp(a->store.filter_source,a->store.catalog.sources[i].id)){next=i+1;break;}
    a->store.filter_source[0]=0;
    for(int i=next;i<a->store.catalog.source_count;i++)if(a->store.catalog.sources[i].enabled){copy_text(a->store.filter_source,sizeof(a->store.filter_source),a->store.catalog.sources[i].id);break;}
    a->store.page=0;
}
static int store_rows(App *a,int *rows){
    int count=0;
    if(a->store.tab==1)for(int i=0;i<a->app_count;i++)if(store_matches(a,a->apps[i].name,a->apps[i].description))rows[count++]=-i-1;
    for(int i=0;i<a->store.catalog.count;i++){
        PaperOSStoreEntry *e=&a->store.catalog.entries[i];
        if(a->store.tab!=1&&((!a->store.show_incompatible&&e->reason[0])||(a->store.filter_source[0]&&strcmp(e->source_id,a->store.filter_source))))continue;
        if(!store_matches(a,e->name,e->description)||(a->store.tab==2&&!e->update))continue;
        if(a->store.tab==1&&(!e->installed[0]||strcmp(e->kind,"koplugin")))continue;
        bool duplicate=false;
        for(int j=0;j<count;j++)if(rows[j]>=0&&!strcmp(a->store.catalog.entries[rows[j]].id,e->id))duplicate=true;
        if(!duplicate)rows[count++]=i;
    }
    return count;
}
static void store_library(App *a){
    store_tick(a);PaperOSStoreUI *u=&a->store;PaperOSServices *s=&a->ui.services;
    const char *message=a->ui.message[0]?a->ui.message:s->store_message;
    header(a,"应用商店","");
    const char *filter=store_filter_name(a);button(30,101,247,33,filter,false);button(292,101,158,33,u->show_incompatible?"全部类型":"可安装",!u->show_incompatible);
    button(465,101,105,33,u->query[0]?"清除搜索":"搜索",false);
    const char *tabs[]={"发现","已安装","更新"};
    for(int i=0;i<3;i++)button(30+183*i,166,174,48,tabs[i],u->tab==i);
    int rows[PAPEROS_STORE_MAX+PAPEROS_MAX_APPS],count=store_rows(a,rows);
    if(u->page*4>=count)u->page=0;
    for(int row=0;row<4&&u->page*4+row<count;row++){
        int index=rows[u->page*4+row],y=235+91*row;char subtitle[320];
        const char *name;
        if(index<0){PaperOSApp *p=&a->apps[-index-1];name=p->name;snprintf(subtitle,sizeof(subtitle),"%s  ·  PaperOS 应用",p->version);}
        else{PaperOSStoreEntry *e=&u->catalog.entries[index];name=e->name;snprintf(subtitle,sizeof(subtitle),"%.24s · %s%s",e->version,store_kind(e),e->reason[0]?" · 需适配":e->update?" · 可更新":e->installed[0]?" · 已安装":"");}
        box(30,y,540,80,170);text(47,y+9,27,name,504,0);text(47,y+46,18,subtitle,504,65);
    }
    if(!count){
        const char *empty=u->query[0]?"没有匹配的应用":u->tab==2?"已是最新版本":u->tab==1?"还没有安装应用":"暂时没有在线应用目录";
        text(30,265,28,empty,540,0);text(30,314,21,u->tab==0?"连接 Wi-Fi 后点刷新，也可导入下载链接。":"可从「发现」下载，或打开本地应用包。",540,70);
    }
    text(30,592,16,u->query[0]?u->query:message,540,65);
    button(30,616,102,34,"应用源",false);button(143,616,116,34,"下载链接",false);button(270,616,124,34,"本地包",false);button(435,616,135,34,s->store_busy?"处理中":"刷新",false);
    button(30,665,110,40,"上页",false);button(460,665,110,40,"下页",false);
    char page[64];snprintf(page,sizeof(page),"%d / %d  ·  %d 款",u->page+1,count?(count+3)/4:1,count);text(300-text_width(page,21)/2,675,21,page,300,60);
}
static void store_details(App *a){
    store_tick(a);PaperOSStoreEntry *e=store_selected(a);PaperOSServices *s=&a->ui.services;
    if(!e){header(a,"下载链接","");text(30,183,24,s->store_message,540,0);button(30,660,540,42,"返回应用商店",false);return;}
    header(a,e->name,e->version);text(30,174,24,e->description,540,25);
    char b[320];snprintf(b,sizeof(b),"应用源：%s",e->source);text(30,254,21,b,540,60);
    snprintf(b,sizeof(b),"%s  ·  %s%s",store_kind(e),e->installed[0]?"已安装 ":"尚未安装",e->installed);text(30,297,21,b,540,60);
    text(30,346,21,e->reason[0]?e->reason:!strcmp(e->kind,"koplugin")?"在 KOReader 内使用；安装后重新打开阅读器。":"安装和更新会保留已有的个人数据。",540,50);
    bool current=!strcmp(s->store_key,e->key),ready=current&&!strcmp(s->store_phase,"ready");
    const char *message=a->ui.message[0]?a->ui.message:current?s->store_message:"";text(30,412,22,message,540,0);
    if(current&&s->store_busy){box(30,478,540,10,130);int progress=s->store_progress;if(progress<0)progress=0;if(progress>100)progress=100;rect(32,480,536*progress/100,6,0);}
    else if(ready){snprintf(b,sizeof(b),"SHA-256  %.20s…",s->store_digest);text(30,473,20,b,540,0);text(30,501,18,"核对来源后，点确认安装",540,60);}
    const char *primary=ready?"确认安装":s->store_busy?"正在处理":e->update?"下载更新":e->installed[0]?"重新下载":"下载";
    int native=store_native(a,e->id),reader=store_native(a,"org.paperos.koreader");
    const char *secondary=s->store_busy?"取消下载":native>=0?"打开":!strcmp(e->kind,"koplugin")&&reader>=0?"打开阅读器":"返回列表";
    button(30,542,261,58,primary,!s->store_busy&&!e->reason[0]);button(309,542,261,58,secondary,false);
    if(!strcmp(e->kind,"koplugin")&&e->installed[0])button(30,611,261,32,a->store.confirm_remove?"确认卸载插件":"卸载插件",false);
    button(30,660,540,42,"返回应用商店",false);
}
static void store_sources(App *a){
    store_tick(a);PaperOSStoreUI *u=&a->store;header(a,"应用源","管理社区目录和自定义仓库");
    if(u->source_page*4>=u->catalog.source_count)u->source_page=0;
    for(int row=0;row<4&&u->source_page*4+row<u->catalog.source_count;row++){
        PaperOSStoreSource *s=&u->catalog.sources[u->source_page*4+row];int y=164+96*row;
        box(30,y,540,86,170);text(44,y+8,24,s->name,390,0);text(44,y+49,17,s->error[0]?s->error:s->url,508,65);button(448,y+8,108,35,s->enabled?"已启用":"已停用",s->enabled);
    }
    if(u->source_selected[0])button(30,557,261,32,u->confirm_source_remove?"确认移除应用源":"移除所选应用源",false);
    else if(a->ui.message[0])text(30,560,20,a->ui.message,540,0);
    button(30,606,261,38,"社区源",false);button(309,606,261,38,"添加网址",false);
    button(30,665,110,40,"上页",false);button(150,665,300,40,"返回应用商店",false);button(460,665,110,40,"下页",false);
}
static void store_community(App *a){
    store_tick(a);PaperOSStoreCatalog *catalog=&a->store.catalog;header(a,"社区应用源","选择添加，或从应用源页面输入网址");
    for(int i=0;i<catalog->preset_count&&i<4;i++){
        PaperOSStoreSource *p=&catalog->presets[i];int y=164+106*i;
        box(30,y,540,94,170);text(44,y+9,25,p->name,360,0);text(44,y+58,18,p->error,500,65);
        button(448,y+8,108,35,p->enabled?"已添加":"添加",!p->enabled);
    }
    text(30,602,19,a->ui.message[0]?a->ui.message:"添加后，返回商店点刷新即可获取目录。",540,65);
    button(30,665,540,40,"返回应用源",false);
}
static bool store_tap(App *a,int x,int y){
    PaperOSStoreUI *u=&a->store;PaperOSServices *s=&a->ui.services;
    if(a->screen==APP_LIBRARY&&!a->show_packages){
        store_tick(a);
        if(y>=101&&y<136){if(x>=465){if(u->query[0]){u->query[0]=0;u->page=0;}else a->ui.input_task=10;}else if(x>=30&&x<277)store_filter_next(a);else if(x>=292&&x<450){u->show_incompatible=!u->show_incompatible;u->page=0;}}
        else if(y>=166&&y<214&&x>=30&&x<570){u->tab=(x-30)/183;if(u->tab>2)u->tab=2;u->page=0;a->ui.message[0]=0;reload_apps(a);dash_command(a,"store-sync",NULL);}
        else if(y>=235&&y<599&&(y-235)%91<80&&x>=30&&x<570){
            int rows[PAPEROS_STORE_MAX+PAPEROS_MAX_APPS],count=store_rows(a,rows),index=u->page*4+(y-235)/91;
            if(index<count){int target=rows[index];a->ui.message[0]=0;if(target<0){a->selected_app=-target-1;a->confirm_remove=false;a->app_message[0]=0;a->screen=APP_DETAILS;}else{copy_text(u->selected,sizeof(u->selected),u->catalog.entries[target].key);u->confirm_remove=false;a->screen=STORE_DETAILS;}}
        }else if(y>=616&&y<650){if(x>=30&&x<132){a->screen=STORE_SOURCES;a->ui.message[0]=0;}else if(x>=143&&x<259)a->ui.input_task=11;else if(x>=270&&x<394){a->show_packages=true;a->app_page=0;reload_apps(a);}else if(x>=435)dash_command(a,"store-refresh",NULL);}
        else if(y>=665&&y<705){int rows[PAPEROS_STORE_MAX+PAPEROS_MAX_APPS],count=store_rows(a,rows);if(x>=30&&x<140&&u->page>0)u->page--;else if(x>=460&&x<570&&(u->page+1)*4<count)u->page++;}
        return true;
    }
    if(a->screen==STORE_DETAILS){
        if(y>=660&&y<702){a->screen=APP_LIBRARY;return true;}
        PaperOSStoreEntry *e=store_selected(a);if(!e)return true;
        if(y>=542&&y<600){
            if(x>=30&&x<291&&!s->store_busy&&!e->reason[0]){
                if(!strcmp(s->store_key,e->key)&&!strcmp(s->store_phase,"ready")){const char *args[]={"id",s->store_job,"digest",s->store_digest,NULL};dash_command(a,"store-install",args);}
                else{const char *args[]={"key",e->key,NULL};dash_command(a,"store-download",args);}
            }else if(x>=309&&x<570){
                if(s->store_busy)dash_command(a,"store-cancel",NULL);
                else{int index=store_native(a,e->id);if(index<0&&!strcmp(e->kind,"koplugin"))index=store_native(a,"org.paperos.koreader");if(index>=0)a->launch_app=index;else a->screen=APP_LIBRARY;}
            }
        }else if(y>=611&&y<643&&x>=30&&x<291&&!strcmp(e->kind,"koplugin")&&e->installed[0]){
            if(!u->confirm_remove)u->confirm_remove=true;else{const char *args[]={"key",e->key,NULL};dash_command(a,"store-remove",args);u->confirm_remove=false;}
        }return true;
    }
    if(a->screen==STORE_SOURCES){
        if(y>=665&&y<705){if(x>=150&&x<450)a->screen=APP_LIBRARY;else if(x>=30&&x<140&&u->source_page>0)u->source_page--;else if(x>=460&&x<570&&(u->source_page+1)*4<u->catalog.source_count)u->source_page++;}
        else if(y>=557&&y<589&&x>=30&&x<291&&u->source_selected[0]){if(!u->confirm_source_remove)u->confirm_source_remove=true;else{const char *args[]={"id",u->source_selected,NULL};dash_command(a,"store-source-remove",args);u->source_selected[0]=0;u->confirm_source_remove=false;}}
        else if(y>=606&&y<644){if(x<291)a->screen=STORE_COMMUNITY;else a->ui.input_task=12;}
        else if(y>=164&&y<548&&x>=448&&x<556&&(y-164)%96<45){int index=u->source_page*4+(y-164)/96;if(index<u->catalog.source_count){const char *args[]={"id",u->catalog.sources[index].id,NULL};dash_command(a,"store-source-toggle",args);}}
        else if(y>=164&&y<548&&x>=30&&x<448){int index=u->source_page*4+(y-164)/96;if(index<u->catalog.source_count){copy_text(u->source_selected,sizeof(u->source_selected),u->catalog.sources[index].id);u->confirm_source_remove=false;}}
        return true;
    }
    if(a->screen==STORE_COMMUNITY){
        if(y>=665&&y<705){a->screen=STORE_SOURCES;return true;}
        if(y>=164&&y<588&&(y-164)%106<94&&x>=30&&x<570){int index=(y-164)/106;if(index<u->catalog.preset_count&&!u->catalog.presets[index].enabled){const char *args[]={"preset",u->catalog.presets[index].id,NULL};dash_command(a,"store-source-add",args);}}
        return true;
    }
    return false;
}
static void store_input(App *a,int task){
    char value[768]={0};const char *title=task==10?"搜索应用":task==11?"安装包或 GitHub 仓库 HTTPS 地址":"应用目录、仓库或根目录 HTTPS 地址";
    int status=paperos_input_text(title,task==10?a->store.query:"",task==10?0:PAPEROS_INPUT_ENGLISH,value,task==10?sizeof(a->store.query):sizeof(value));
    if(status!=PAPEROS_INPUT_ACCEPTED){if(status!=PAPEROS_INPUT_CANCELLED)copy_text(a->ui.message,sizeof(a->ui.message),"系统输入法暂不可用");return;}
    a->ui.message[0]=0;
    if(task==10){copy_text(a->store.query,sizeof(a->store.query),value);a->store.page=0;}
    else{const char *args[]={"url",value,NULL};if(dash_command(a,task==11?"store-import":"store-source-add",args)&&task==11){copy_text(a->store.selected,sizeof(a->store.selected),a->ui.services.store_key);a->screen=STORE_DETAILS;}}
}

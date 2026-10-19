/* Compiled into the separate NDS application, sharing the system overlays. */
static bool nds_obscured(const App *a){return a->ui.services.locked||a->ui.services.alert_id[0]||a->ui.services.transfer_id[0];}
static void nds_side(int x,int y,const char *label){
    box(x+1,y,42,60,160);int size=18;
    text(x+(44-text_width(label,size))/2,y+20,size,label,42,0);
}
static void nds_draw(App *a){
    PaperOSNDS *s=&a->nds;
    if(s->loaded&&!s->menu){
        if(s->frame_valid)paperos_nds_blit(s,pixels);
        nds_side(0,8,"菜单");nds_side(556,8,"刷新");
        nds_side(0,104,"L");nds_side(556,104,"R");
        nds_side(556,432,"吹气");nds_side(0,520,"B");nds_side(556,520,"A");
        nds_side(0,608,"Y");nds_side(556,608,"X");
        nds_side(0,708,"选择");nds_side(556,708,"开始");return;
    }
    header(a,"复苏的逆转",s->loaded?"NDS · 本机运行 · 游戏已暂停":"NDS · 尚未导入游戏");
    if(!s->loaded){
        centered(233,36,"等待导入你的游戏");
        text(30,311,25,"在电脑上选择已有的汉化 .nds 文件，",540,0);
        text(30,353,25,"导入后即可在这里离线游玩。",540,0);
        text(30,428,22,"推荐图片汉化补完、大字体版本。",540,65);
        text(30,509,22,s->message,540,65);
        button(20,617,560,58,"重新检查游戏",true);
        button(20,718,560,58,"返回主页",false);return;
    }
    button(20,166,560,58,"继续游戏",true);
    button(20,247,273,52,"即时保存",false);button(307,247,273,52,"读取即时存档",false);
    text(30,330,23,"方向键 · 点击后回到游戏",540,65);
    button(264,370,72,58,"↑",false);button(180,442,72,58,"←",false);
    button(264,442,72,58,"↓",false);button(348,442,72,58,"→",false);
    char status[128];snprintf(status,sizeof(status),"模拟速度 %.0f%% · 面板按需刷新",s->measured_fps/60*100);
    text(30,532,21,s->frames?status:"上下双屏两倍显示，下屏直接触摸",540,65);
    text(30,573,22,s->message,540,0);
    button(20,632,560,58,"保存并返回主页",true);
    button(20,718,560,52,s->confirm_exit?"确认放弃本次进度并返回":"不保存本次进度返回",false);
}
static void nds_tap(App *a,int x,int y){
    PaperOSNDS *s=&a->nds;if(!s->menu&&s->loaded)return;
    if(!s->loaded){
        if(y>=617&&y<675){paperos_nds_close(s);paperos_nds_open(s);}
        if(y>=718&&y<776){s->skip_exit_save=true;a->return_requested=true;}
    }else if(y>=166&&y<224){s->menu=false;paperos_nds_release(s);}
    else if(y>=247&&y<299){if(x<300)paperos_nds_save(s,false);else paperos_nds_load(s,false);}
    else if(y>=370&&y<428&&x>=264&&x<336){paperos_nds_pulse(s,4);s->menu=false;}
    else if(y>=442&&y<500){
        if(x>=180&&x<252){paperos_nds_pulse(s,6);s->menu=false;}
        else if(x>=264&&x<336){paperos_nds_pulse(s,5);s->menu=false;}
        else if(x>=348&&x<420){paperos_nds_pulse(s,7);s->menu=false;}
    }else if(y>=632&&y<690){if(paperos_nds_save(s,true)){s->skip_exit_save=true;a->return_requested=true;}}
    else if(y>=718&&y<770){
        if(s->confirm_exit){s->skip_exit_save=true;a->return_requested=true;}
        else{s->confirm_exit=true;copy_text(s->message,sizeof(s->message),"再次点击确认；原有存档不会删除");}
    }
    if(y<718)s->confirm_exit=false;
    a->ui.display_transition=true;a->dirty=true;
}

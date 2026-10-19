#define _POSIX_C_SOURCE 200809L
#include "player.h"
#include "sha256.h"
#include <libretro.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static PaperOSNDS *active;
static unsigned char gray565[65536];
static void log_core(enum retro_log_level level,const char *format,...){
    if(level<RETRO_LOG_WARN)return;
    va_list args;va_start(args,format);vfprintf(stderr,format,args);va_end(args);
}
static bool environment(unsigned command,void *data){
    switch(command){
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:((struct retro_log_callback *)data)->log=log_core;return true;
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:*(const char **)data=active->data;return true;
    case RETRO_ENVIRONMENT_GET_LANGUAGE:*(unsigned *)data=RETRO_LANGUAGE_JAPANESE;return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:return *(enum retro_pixel_format *)data==RETRO_PIXEL_FORMAT_RGB565;
    case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:*(bool *)data=false;return true;
    case RETRO_ENVIRONMENT_SET_VARIABLES:
    case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
    case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
    case RETRO_ENVIRONMENT_SET_GEOMETRY:return true;
    case RETRO_ENVIRONMENT_GET_VARIABLE:{
        struct retro_variable *v=data;
        static const char *const options[][2]={
            {"desmume_internal_resolution","256x192"},{"desmume_num_cores","1"},
            {"desmume_cpu_mode","jit"},{"desmume_jit_block_size","12"},
            {"desmume_screens_layout","top/bottom"},{"desmume_pointer_type","touch"},
            {"desmume_pointer_mouse","enabled"},{"desmume_load_to_memory","enabled"},
            {"desmume_frameskip","9"},{"desmume_screens_gap","0"},
            {"desmume_mic_mode","random"},{"desmume_mic_force_enable","disabled"},
            {"desmume_firmware_language","Japanese"}};
        for(size_t i=0;i<sizeof(options)/sizeof(options[0]);i++)if(!strcmp(v->key,options[i][0])){v->value=options[i][1];return true;}
        v->value=NULL;return false;
    }
    default:return false;
    }
}
static void video(const void *data,unsigned width,unsigned height,size_t pitch){
    if(!data||width!=256||height!=384||pitch<512)return;
    for(unsigned y=0;y<384;y++){
        const uint16_t *row=(const uint16_t *)((const unsigned char *)data+y*pitch);
        for(unsigned x=0;x<256;x++){
            unsigned char shade=gray565[row[x]];
            size_t i=y*256+x;if(active->frame[i]!=shade){active->frame[i]=shade;active->changed=true;}
        }
    }
    active->frame_valid=true;active->video_frames++;
}
static void audio(int16_t a,int16_t b){(void)a;(void)b;}
static size_t audio_batch(const int16_t *data,size_t frames){(void)data;return frames;}
static void poll_input(void){}
static int16_t input(unsigned port,unsigned device,unsigned index,unsigned id){
    (void)index;if(port)return 0;
    if(device==RETRO_DEVICE_JOYPAD&&id<16)return !!((active->buttons|active->pulse_buttons)&(1U<<id));
    if(device==RETRO_DEVICE_POINTER){
        if(id==RETRO_DEVICE_ID_POINTER_PRESSED)return active->touching||active->touch_frames;
        if(id==RETRO_DEVICE_ID_POINTER_X)return (int16_t)active->pointer_x;
        if(id==RETRO_DEVICE_ID_POINTER_Y)return (int16_t)active->pointer_y;
    }
    return 0;
}
double paperos_nds_now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static bool read_all(int fd,void *data,size_t size){
    unsigned char *p=data;while(size){ssize_t n=read(fd,p,size);if(n<0&&errno==EINTR)continue;if(n<=0)return false;p+=n;size-=(size_t)n;}return true;
}
static bool write_all(int fd,const void *data,size_t size){
    const unsigned char *p=data;while(size){ssize_t n=write(fd,p,size);if(n<0&&errno==EINTR)continue;if(n<=0)return false;p+=n;size-=(size_t)n;}return true;
}
static uint32_t le32(const unsigned char *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void put32(unsigned char *p,uint32_t n){for(unsigned i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static bool identify(PaperOSNDS *s){
    int fd=open(s->rom,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);struct stat st;unsigned char header[512];
    if(fd<0){snprintf(s->message,sizeof(s->message),errno==ENOENT?"尚未导入游戏文件":"无法读取游戏文件");return false;}
    bool okay=!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_size>=512&&st.st_size<=128*1024*1024&&read_all(fd,header,sizeof(header));
    if(okay){
        uint32_t a=le32(header+0x20),n=le32(header+0x2c),b=le32(header+0x30),m=le32(header+0x3c);
        okay=n&&m&&a>=512&&b>=512&&(uint64_t)a+n<=(uint64_t)st.st_size&&(uint64_t)b+m<=(uint64_t)st.st_size;
    }
    NDSHash hash;nds_hash_init(&hash);
    if(okay){
        nds_hash_update(&hash,header,sizeof(header));unsigned char chunk[32768];ssize_t n;
        while((n=read(fd,chunk,sizeof(chunk)))!=0){if(n<0){if(errno==EINTR)continue;okay=false;break;}nds_hash_update(&hash,chunk,(size_t)n);}
        if(okay)nds_hash_finish(&hash,s->digest);
    }
    close(fd);if(!okay)snprintf(s->message,sizeof(s->message),"文件不是支持的 NDS 镜像（最大128 MiB）");return okay;
}
static bool state_path(const PaperOSNDS *s,bool resume,char *out,size_t size){return snprintf(out,size,"%s/%s.state",s->data,resume?"resume":"quick")<(int)size;}
static bool state_header(const PaperOSNDS *s,const unsigned char h[128],size_t size){
    return !memcmp(h,"PONDSV1",8)&&!memcmp(h+8,PAPEROS_NDS_CORE_REV,40)&&!memcmp(h+48,s->digest,32)&&le32(h+80)==size;
}
bool paperos_nds_save(PaperOSNDS *s,bool resume){
    if(!s->loaded)return false;
    size_t size=retro_serialize_size();unsigned char *body=size&&size<=32*1024*1024?calloc(1,size):NULL;
    bool okay=body&&retro_serialize(body,size);char path[1200],temporary[1240];unsigned char h[128]={0};
    if(okay){memcpy(h,"PONDSV1",8);memcpy(h+8,PAPEROS_NDS_CORE_REV,40);memcpy(h+48,s->digest,32);put32(h+80,(uint32_t)size);nds_hash(body,size,h+88);}
    okay=okay&&state_path(s,resume,path,sizeof(path));int fd=-1;
    if(okay){snprintf(temporary,sizeof(temporary),"%s.tmp.XXXXXX",path);fd=mkstemp(temporary);okay=fd>=0;}
    if(fd>=0){
        okay=write_all(fd,h,sizeof(h))&&write_all(fd,body,size)&&fsync(fd)==0;
        if(close(fd))okay=false;
        if(okay)okay=rename(temporary,path)==0;
        if(!okay)unlink(temporary);
        if(okay){int directory=open(s->data,O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(directory>=0){if(fsync(directory))okay=false;close(directory);}}
    }
    free(body);snprintf(s->message,sizeof(s->message),okay?(resume?"退出进度已保存":"即时存档已保存"):"保存未确认，请检查存储空间");
    if(okay)s->saved_frame=s->frames;
    return okay;
}
bool paperos_nds_load(PaperOSNDS *s,bool resume){
    if(!s->loaded)return false;
    char path[1200];if(!state_path(s,resume,path,sizeof(path)))return false;
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0){snprintf(s->message,sizeof(s->message),"还没有%s存档",resume?"退出":"即时");return false;}
    struct stat st;unsigned char h[128],digest[32];size_t size=retro_serialize_size();
    bool okay=size&&size<=32*1024*1024&&!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_size==(off_t)(sizeof(h)+size)&&read_all(fd,h,sizeof(h))&&state_header(s,h,size);
    unsigned char *body=okay?malloc(size):NULL;okay=okay&&body&&read_all(fd,body,size);close(fd);
    if(okay){nds_hash(body,size,digest);okay=!memcmp(digest,h+88,32);}
    if(okay)okay=retro_unserialize(body,size);
    free(body);
    paperos_nds_release(s);s->deadline=0;s->changed=true;s->frame_valid=false;
    snprintf(s->message,sizeof(s->message),okay?"进度已恢复":"存档损坏或不属于此游戏／核心版本，未加载");return okay;
}
bool paperos_nds_open(PaperOSNDS *s){
    s->menu=true;s->contact_key=-1;s->saved_frame=UINT64_MAX;
    /* The panel presents at most 4 Hz. Keep game/input clocks at 60 Hz while
       rendering 6 Hz in the core, and convert RGB565 through an exact LUT. */
    for(unsigned p=0;p<65536;p++){
        unsigned r=(p>>11)*255/31,g=((p>>5)&63)*255/63,b=(p&31)*255/31;
        gray565[p]=(unsigned char)((((77*r+150*g+29*b)>>8)+8)/17*17);
    }
    if(!identify(s))return false;
    char hex[65];for(unsigned i=0;i<32;i++)snprintf(hex+2*i,3,"%02x",s->digest[i]);
    if(snprintf(s->data,sizeof(s->data),"%s/%s",s->base_data,hex)>=(int)sizeof(s->data))return false;
    struct stat st;
    if((mkdir(s->base_data,0700)&&errno!=EEXIST)||(mkdir(s->data,0700)&&errno!=EEXIST)||stat(s->data,&st)||!S_ISDIR(st.st_mode)){snprintf(s->message,sizeof(s->message),"无法创建应用存档目录");return false;}
    s->frames=s->video_frames=0;s->frame_valid=false;s->deadline=0;
    active=s;retro_set_environment(environment);retro_set_video_refresh(video);retro_set_audio_sample(audio);retro_set_audio_sample_batch(audio_batch);retro_set_input_poll(poll_input);retro_set_input_state(input);
    retro_init();s->initialized=true;struct retro_game_info game={.path=s->rom};s->loaded=retro_load_game(&game);
    if(!s->loaded){snprintf(s->message,sizeof(s->message),"NDS 核心未能加载此游戏");return false;}
    snprintf(s->message,sizeof(s->message),"游戏已加载");
    char path[1200];if(state_path(s,true,path,sizeof(path))&&!access(path,F_OK))paperos_nds_load(s,true);
    return true;
}
void paperos_nds_close(PaperOSNDS *s){
    if(s->loaded){retro_unload_game();s->loaded=false;}
    if(s->initialized){retro_deinit();s->initialized=false;}
    if(active==s)active=NULL;
}
void paperos_nds_release(PaperOSNDS *s){s->buttons=s->pulse_buttons=s->pulse_frames=s->touch_frames=0;s->touching=false;s->contact=false;s->contact_key=-1;}
bool paperos_nds_advance(PaperOSNDS *s,bool blocked){
    if(!s->loaded||s->menu||blocked){if(!s->paused)paperos_nds_release(s);s->paused=true;s->deadline=0;return false;}
    double now=paperos_nds_now();
    if(s->paused||!s->deadline){s->deadline=now;s->measure_at=now;s->measure_frame=s->frames;s->paused=false;}
    if(now<s->deadline)return false;
    retro_run();s->frames++;if(s->pulse_frames&&!--s->pulse_frames)s->pulse_buttons=0;if(s->touch_frames)s->touch_frames--;
    now=paperos_nds_now();s->deadline+=1.0/60.0;if(now-s->deadline>0.2)s->deadline=now;
    if(now-s->measure_at>=1){s->measured_fps=(s->frames-s->measure_frame)/(now-s->measure_at);s->measure_at=now;s->measure_frame=s->frames;}
    return s->changed;
}
bool paperos_nds_point(int x,int y,int *px,int *py){
    if(x<44||x>=556||y<408||y>=792)return false;
    /* Center of each DS pixel; libretro maps absolute coordinates over both screens. */
    int dx=(x-44)/2,dy=192+(y-408)/2;
    *px=(int)(((int64_t)(2*dx+1)*65536)/(2*256))-32768;
    *py=(int)(((int64_t)(2*dy+1)*65536)/(2*384))-32768;return true;
}
bool paperos_nds_contact(PaperOSNDS *s,int x,int y,bool down){
    bool beginning=down&&!s->contact;s->contact=down;
    if(!down){if(s->touching)s->touch_frames=2;s->touching=false;s->buttons=0;s->contact_key=-1;return false;}
    if(s->menu||!s->loaded)return false;
    if(beginning){
        if(x<44&&y<74){s->menu=true;paperos_nds_release(s);return true;}
        if(x>=556&&y<74){return true;} /* UI requests full refresh. */
        if(x<44||x>=556){
            bool right=x>=556;int key=-1;
            if(y>=104&&y<164)key=right?RETRO_DEVICE_ID_JOYPAD_R:RETRO_DEVICE_ID_JOYPAD_L;
            if(y>=432&&y<492&&right)key=RETRO_DEVICE_ID_JOYPAD_L3;
            if(y>=520&&y<580)key=right?RETRO_DEVICE_ID_JOYPAD_A:RETRO_DEVICE_ID_JOYPAD_B;
            if(y>=608&&y<668)key=right?RETRO_DEVICE_ID_JOYPAD_X:RETRO_DEVICE_ID_JOYPAD_Y;
            if(y>=708&&y<768)key=right?RETRO_DEVICE_ID_JOYPAD_START:RETRO_DEVICE_ID_JOYPAD_SELECT;
            s->contact_key=key;if(key>=0){s->buttons=1U<<key;paperos_nds_pulse(s,(unsigned)key);}return false;
        }
    }
    if(s->contact_key<0&&paperos_nds_point(x,y,&s->pointer_x,&s->pointer_y))s->touching=true;
    else s->touching=false;
    return false;
}
void paperos_nds_pulse(PaperOSNDS *s,unsigned id){if(id<16){s->pulse_buttons|=1U<<id;s->pulse_frames=4;}}
void paperos_nds_blit(const PaperOSNDS *s,unsigned char *pixels){
    for(unsigned screen=0;screen<2;screen++)for(unsigned y=0;y<192;y++)for(unsigned x=0;x<256;x++){
        unsigned char shade=s->frame[(screen*192+y)*256+x];unsigned target=(8+screen*400+2*y)*600+44+2*x;
        pixels[target]=pixels[target+1]=pixels[target+600]=pixels[target+601]=shade;
    }
}

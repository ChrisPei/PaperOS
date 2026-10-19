/* Local, short-lived physical-device QA helper. Never shipped in a .papp.
 * Uses the existing evdev device and service socket; opens no network port. */
#define _POSIX_C_SOURCE 200809L
#include "services.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static bool event(int fd,unsigned short type,unsigned short code,int value){
    struct input_event e={.type=type,.code=code,.value=value};
    return write(fd,&e,sizeof(e))==(ssize_t)sizeof(e);
}
static void delay(void){struct timespec t={0,15000000};while(nanosleep(&t,&t)&&errno==EINTR){}}
static int contact(int x0,int y0,int x1,int y1){
    if(x0<0||x0>=600||x1<0||x1>=600||y0<0||y0>=800||y1<0||y1>=800)return 2;
    int fd=open("/dev/input/event0",O_RDWR|O_CLOEXEC);if(fd<0)return 3;
    struct input_absinfo ax,ay;
    bool okay=ioctl(fd,EVIOCGABS(ABS_MT_POSITION_X),&ax)==0&&ioctl(fd,EVIOCGABS(ABS_MT_POSITION_Y),&ay)==0;
    okay=okay&&event(fd,EV_ABS,ABS_MT_SLOT,0)&&event(fd,EV_ABS,ABS_MT_TRACKING_ID,12345);
    for(int step=0;step<=10&&okay;step++){
        int x=x0+(x1-x0)*step/10,y=y0+(y1-y0)*step/10;
        okay=event(fd,EV_ABS,ABS_MT_POSITION_X,ax.minimum+x*(ax.maximum-ax.minimum)/600)&&
             event(fd,EV_ABS,ABS_MT_POSITION_Y,ay.minimum+y*(ay.maximum-ay.minimum)/800)&&
             event(fd,EV_KEY,BTN_TOUCH,1)&&event(fd,EV_SYN,SYN_REPORT,0);
        delay();
    }
    /* Always release even if injection failed partway through. */
    bool released=event(fd,EV_ABS,ABS_MT_TRACKING_ID,-1)&&event(fd,EV_KEY,BTN_TOUCH,0)&&event(fd,EV_SYN,SYN_REPORT,0);
    close(fd);return okay&&released?0:4;
}
static int capture(void){
    int fd=open("/dev/fb0",O_RDONLY|O_CLOEXEC);if(fd<0)return 3;
    struct fb_var_screeninfo v;struct fb_fix_screeninfo f;
    if(ioctl(fd,FBIOGET_VSCREENINFO,&v)||ioctl(fd,FBIOGET_FSCREENINFO,&f)||v.bits_per_pixel!=8||v.xres!=600||v.yres!=800){close(fd);return 4;}
    unsigned char row[600];printf("P5\n600 800\n255\n");
    for(unsigned y=0;y<v.yres;y++){
        off_t offset=(off_t)(y+v.yoffset)*f.line_length+v.xoffset;
        if(pread(fd,row,sizeof(row),offset)!=(ssize_t)sizeof(row)||fwrite(row,1,sizeof(row),stdout)!=sizeof(row)){close(fd);return 4;}
    }
    close(fd);return fflush(stdout)?4:0;
}
int main(int argc,char **argv){
    if(argc==2&&!strcmp(argv[1],"capture"))return capture();
    if(argc==4&&!strcmp(argv[1],"tap"))return contact(atoi(argv[2]),atoi(argv[3]),atoi(argv[2]),atoi(argv[3]));
    if(argc==6&&!strcmp(argv[1],"swipe"))return contact(atoi(argv[2]),atoi(argv[3]),atoi(argv[4]),atoi(argv[5]));
    if(argc==2&&(!strcmp(argv[1],"lock-now")||!strcmp(argv[1],"lock-unlock"))){
        char message[256];bool okay=paperos_service_command(argv[1],NULL,message,sizeof(message));
        if(!okay)fprintf(stderr,"%s\n",message);
        return okay?0:4;
    }
    return 2;
}

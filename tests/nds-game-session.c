/* Bounded headless game inspection. Not part of the distributed application. */
#define _POSIX_C_SOURCE 200809L
#include "player.h"
#include <assert.h>
#include <ctype.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <unistd.h>
static void frames(PaperOSNDS *s,unsigned count){s->menu=false;while(count--){s->deadline=0;paperos_nds_advance(s,false);}}
int main(int argc,char **argv){
    if(argc!=4)return 2;
    alarm(100);setvbuf(stdout,NULL,_IOLBF,0);
    const char *lock=getenv("PAPEROS_QA_APP_LOCK");
    if(lock){
        int fd=open(lock,O_RDWR|O_CLOEXEC|O_NOFOLLOW);
        if(fd<0||flock(fd,LOCK_EX|LOCK_NB)){
            fprintf(stderr,"Close the foreground PaperOS app before headless game QA\n");return 6;
        }
        /* Retain the manager lock until exit, as a normal foreground app does. */
    }
    static PaperOSNDS state;snprintf(state.rom,sizeof(state.rom),"%s",argv[1]);snprintf(state.base_data,sizeof(state.base_data),"%s",argv[2]);
    mkdir(argv[3],0700);
    if(!paperos_nds_open(&state)){fprintf(stderr,"%s\n",state.message);return 3;}
    state.menu=false;
    char line[256];unsigned total=0;
    while(fgets(line,sizeof(line),stdin)){
        unsigned count;int x,y;char name[64];
        if(sscanf(line,"run %u",&count)==1){
            if(!count||count>1200||total+count>3000)return 2;
            double start=paperos_nds_now();frames(&state,count);double elapsed=paperos_nds_now()-start;total+=count;
            printf("PAPEROS_NDS_GAME {\"frames\":%u,\"seconds\":%.6f,\"unthrottled_emulated_fps\":%.3f}\n",count,elapsed,count/elapsed);
        }else if(sscanf(line,"tap %d %d",&x,&y)==2){
            if(x<0||x>255||y<0||y>191)return 2;
            paperos_nds_contact(&state,44+x*2,408+y*2,true);frames(&state,3);
            paperos_nds_contact(&state,44+x*2,408+y*2,false);frames(&state,3);
        }else if(sscanf(line,"key %63s",name)==1){
            unsigned id=!strcmp(name,"A")?8:!strcmp(name,"B")?0:!strcmp(name,"START")?3:!strcmp(name,"MIC")?14:99;
            if(id==99)return 2;
            paperos_nds_pulse(&state,id);frames(&state,6);
        }else if(sscanf(line,"shot %63s",name)==1){
            for(char *p=name;*p;p++)if(!isalnum((unsigned char)*p)&&*p!='-'&&*p!='_')return 2;
            char path[1600];snprintf(path,sizeof(path),"%s/%s.pgm",argv[3],name);FILE *f=fopen(path,"wb");if(!f)return 4;
            fprintf(f,"P5\n256 384\n255\n");bool okay=fwrite(state.frame,1,sizeof(state.frame),f)==sizeof(state.frame);if(fclose(f))okay=false;if(!okay)return 4;
            printf("PAPEROS_NDS_SHOT %s\n",name);
        }else return 2;
    }
    bool saved=paperos_nds_save(&state,true);paperos_nds_close(&state);return saved?0:5;
}

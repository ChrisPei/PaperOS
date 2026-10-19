#define _POSIX_C_SOURCE 200809L
#include "player.h"
#include <libretro.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
extern int paperos_nds_test_touch(int x,int y,int pressed);
extern int paperos_nds_test_microphone(void);
extern int paperos_nds_test_noise_range(void);
static uint32_t counter(void){uint32_t n=0;memcpy(&n,(char *)retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM)+0x1000,4);return n;}
static uint32_t key(void){uint32_t n=0;memcpy(&n,(char *)retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM)+0x1004,4);return n;}
static void steps(PaperOSNDS *s,unsigned n){s->menu=false;while(n--){s->deadline=0;paperos_nds_advance(s,false);}}
static void restore_file(const char *path,const void *data,size_t size){FILE *f=fopen(path,"wb");assert(f);assert(fwrite(data,1,size,f)==size);assert(!fclose(f));}
int main(int argc,char **argv){
    assert(argc>=3);alarm(55);
    static PaperOSNDS s;snprintf(s.rom,sizeof(s.rom),"%s",argv[1]);snprintf(s.base_data,sizeof(s.base_data),"%s",argv[2]);
    assert(paperos_nds_open(&s));
    if(argc>3){assert(counter()==strtoul(argv[3],NULL,10));printf("PAPEROS_NDS_REOPEN {\"counter\":%u,\"passed\":true}\n",counter());paperos_nds_close(&s);return 0;}
    int x,y;assert(!paperos_nds_point(43,408,&x,&y));assert(!paperos_nds_point(44,407,&x,&y));
    assert(!paperos_nds_point(556,500,&x,&y));assert(!paperos_nds_point(100,792,&x,&y));
    assert(paperos_nds_point(44,408,&x,&y));assert((x+32768)*256/65536==0&&(y+32768)*384/65536==192);
    assert(paperos_nds_point(555,791,&x,&y));assert((x+32768)*256/65536==255&&(y+32768)*384/65536==383);
    steps(&s,12);assert(s.frame_valid&&counter()>0);
    paperos_nds_contact(&s,44+72*2,408+37*2,true);steps(&s,2);assert(paperos_nds_test_touch(72,37,1));
    paperos_nds_contact(&s,188,482,false);steps(&s,4);assert(paperos_nds_test_touch(0,0,0));
    paperos_nds_contact(&s,580,540,true);steps(&s,2);assert(key()==1022);paperos_nds_contact(&s,580,540,false);steps(&s,5);assert(key()==1023);
    paperos_nds_contact(&s,580,450,true);steps(&s,2);assert(paperos_nds_test_microphone());assert(paperos_nds_test_noise_range()>0);paperos_nds_contact(&s,580,450,false);steps(&s,5);assert(!paperos_nds_test_microphone());assert(paperos_nds_test_noise_range()==0);
    uint32_t paused=counter();s.menu=false;paperos_nds_advance(&s,true);assert(counter()==paused&&!s.buttons&&!s.touching);
    double start=paperos_nds_now();uint64_t frame=s.frames;s.menu=false;
    while(s.frames-frame<30){paperos_nds_advance(&s,false);struct timespec wait={0,1000000};nanosleep(&wait,NULL);}
    double paced=paperos_nds_now()-start;assert(paced>=0.45&&paced<1.5);
    uint32_t saved=counter();assert(paperos_nds_save(&s,false));assert(paperos_nds_save(&s,true));
    steps(&s,5);assert(counter()>saved);assert(paperos_nds_load(&s,false));assert(counter()==saved);
    char path[1280];snprintf(path,sizeof(path),"%s/quick.state",s.data);
    FILE *f=fopen(path,"rb");assert(f);assert(!fseek(f,0,SEEK_END));long size=ftell(f);assert(size>128);rewind(f);unsigned char *data=malloc((size_t)size);assert(data);assert(fread(data,1,(size_t)size,f)==(size_t)size);fclose(f);
    data[size-1]^=1;restore_file(path,data,(size_t)size);assert(!paperos_nds_load(&s,false));assert(counter()==saved);data[size-1]^=1;
    data[48]^=1;restore_file(path,data,(size_t)size);assert(!paperos_nds_load(&s,false));assert(counter()==saved);data[48]^=1;
    restore_file(path,data,128);assert(!paperos_nds_load(&s,false));assert(counter()==saved);
    restore_file(path,data,(size_t)size);free(data);assert(paperos_nds_load(&s,false));
    printf("PAPEROS_NDS_PLAYER_TEST {\"passed\":true,\"counter\":%u,\"touch\":true,\"microphone_flag\":true,\"a_button\":true,\"paced_30_frames_seconds\":%.6f,\"atomic_state_roundtrip\":true,\"corrupt_state_rejected\":true,\"wrong_rom_state_rejected\":true,\"truncated_state_rejected\":true}\n",saved,paced);
    paperos_nds_close(&s);return 0;
}

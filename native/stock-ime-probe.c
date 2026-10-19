/* Local compatibility probe for the stock KT3 Chinese predictor plugin.
 * The plugin and dictionaries are not distributed with this source.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static char committed[256];
static int callback(unsigned previous,unsigned flags,const char *value) {
    (void)previous; (void)flags;
    if(value) snprintf(committed,sizeof(committed),"%s",value);
    return 0;
}

int main(int argc,char **argv) {
    if(argc>=3 && !strcmp(argv[1],"--root")) {
        if(chroot(argv[2]) || chdir("/")) { perror("IME compatibility root"); return 3; }
        argc-=2; argv+=2;
    }
    if(argc>2 || (argc==2 && (!argv[1][0] || strlen(argv[1])>32))) return 2;
    if(argc==2) for(const unsigned char *p=(unsigned char*)argv[1];*p;p++) if(*p<'a' || *p>'z') return 2;
    void *library=dlopen("/usr/share/keyboard/zh_CN/libpredictor.so.1.0",RTLD_NOW|RTLD_LOCAL);
    if(!library) { fprintf(stderr,"Predictor load failed: %s\n",dlerror()); return 3; }
    void *(*load)(void*)=dlsym(library,"load");
    if(!load) return 3;
    void *callbacks[16]={0};
    for(unsigned i=0;i<16;i++) callbacks[i]=(void*)callback;
    uintptr_t *plugin=load(callbacks);
    if(!plugin) { fprintf(stderr,"Predictor initialization failed\n"); return 3; }
    Dl_info info;
    if(!dladdr((void*)load,&info)) return 3;
    const uintptr_t expected[8]={0x1d74,0x13cc,0x24d0,0x2284,0x1050,0x15e4,0x18d0,0x1068};
    for(unsigned i=0;i<8;i++) {
        if(plugin[i]-(uintptr_t)info.dli_fbase!=expected[i]) {
            fprintf(stderr,"Unsupported predictor ABI\n"); return 4;
        }
    }
    void (*reset)(unsigned,unsigned)=(void*)plugin[1];
    int (*key)(unsigned,unsigned)=(void*)plugin[5];
    void (*candidates)(char**,int*,unsigned)=(void*)plugin[7];
    void (*select_phrase)(int,unsigned)=(void*)plugin[6];
    void (*destroy)(void*)=(void*)plugin[0];
    char request[128],*values[500]={0}; int count=0,result=0;
    do {
        const char *query;
        if(argc==2) query=argv[1];
        else {
            if(!fgets(request,sizeof(request),stdin)) break;
            size_t length=strlen(request);
            if(!length || request[length-1]!='\n') { result=4; break; }
            request[length-1]=0;
            if(request[0]=='S' && request[1]=='\t') {
                char *end; long index=strtol(request+2,&end,10);
                if(end==request+2 || *end || index<0 || index>=count) { result=4; break; }
                committed[0]=0; select_phrase((int)index,0);
                if(!committed[0]) { result=4; break; }
                printf("paperos-ime-commit\t%s\n",committed); fflush(stdout); continue;
            }
            if(request[0]!='Q' || request[1]!='\t') { result=4; break; }
            query=request+2;
        }
        if(strlen(query)>32) { result=4; break; }
        for(const unsigned char *p=(unsigned char*)query;*p;p++) if(*p<'a' || *p>'z') { result=4; break; }
        if(result) break;
        reset(0,0);
        for(const unsigned char *p=(unsigned char*)query;*p;p++) key(*p,0);
        count=16; candidates(values,&count,0);
        if(count<0 || count>16) { result=4; break; }
        if(argc==2) printf("query=%s\ncandidates=%d\n",query,count);
        else printf("paperos-ime-v1\t%d\n",count);
        for(int i=0;i<count;i++) {
            if(!values[i] || strnlen(values[i],128)>=128 || strpbrk(values[i],"\r\n\t")) { result=4; break; }
            if(argc==2) printf("%d\t%s\n",i,values[i]); else puts(values[i]);
        }
        fflush(stdout);
        if(argc==2) { if(count) { select_phrase(0,0); printf("commit=%s\n",committed); } else result=5; }
    } while(argc==1 && !result);
    destroy(plugin);
    dlclose(library);
    return result;
}

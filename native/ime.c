#define _POSIX_C_SOURCE 200809L
#include "ime.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static long milliseconds(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec*1000L+t.tv_nsec/1000000L; }
void paperos_ime_close(PaperOSIME *ime) {
    if(ime->input>=0) close(ime->input);
    if(ime->output>=0) close(ime->output);
    if(ime->child>0) { kill(ime->child,SIGTERM); for(int i=0;i<10;i++) { if(waitpid(ime->child,NULL,WNOHANG)>0) { ime->child=0; break; } poll(NULL,0,20); } if(ime->child>0) { kill(ime->child,SIGKILL); while(waitpid(ime->child,NULL,0)<0 && errno==EINTR) {} } }
    ime->input=ime->output=-1; ime->child=0;
}
static bool line(PaperOSIME *ime,char *buffer,size_t size) {
    long deadline=milliseconds()+1500; size_t position=0;
    while(position+1<size) {
        long remaining=deadline-milliseconds(); if(remaining<=0) return false;
        struct pollfd p={ime->output,POLLIN,0};
        int ready=poll(&p,1,(int)remaining); if(ready<0 && errno==EINTR) continue; if(ready<=0) return false;
        char ch; if(read(ime->output,&ch,1)!=1) return false;
        if(ch=='\n') { buffer[position]=0; return true; }
        if((unsigned char)ch<32 && ch!='\t') return false;
        buffer[position++]=ch;
    }
    return false;
}
static bool send_request(PaperOSIME *ime,const char *request) {
    size_t length=strlen(request),done=0;
    if(ime->input<0) return false;
    while(done<length) { ssize_t n=write(ime->input,request+done,length-done); if(n<0 && errno==EINTR) continue; if(n<=0) return false; done+=(size_t)n; }
    return true;
}
bool paperos_ime_query(PaperOSIME *ime,const char *text,char values[16][128],int *count) {
    *count=0; if(strlen(text)>32) return false;
    for(const unsigned char *p=(const unsigned char*)text;*p;p++) if(*p<'a' || *p>'z') return false;
    char request[40],response[160]; snprintf(request,sizeof(request),"Q\t%s\n",text);
    if(!send_request(ime,request) || !line(ime,response,sizeof(response)) || strncmp(response,"paperos-ime-v1\t",15)) return false;
    char *end; errno=0; long number=strtol(response+15,&end,10); if(errno || end==response+15 || *end || number<0 || number>16) return false;
    for(int i=0;i<number;i++) if(!line(ime,values[i],128) || !values[i][0] || strchr(values[i],'\t')) return false;
    *count=(int)number; return true;
}
bool paperos_ime_commit(PaperOSIME *ime,int index,char value[128]) {
    if(index<0 || index>=16) return false;
    char request[32],response[160]; snprintf(request,sizeof(request),"S\t%d\n",index);
    if(!send_request(ime,request) || !line(ime,response,sizeof(response)) || strncmp(response,"paperos-ime-commit\t",19)) return false;
    size_t length=strlen(response+19); if(!length || length>=128 || strchr(response+19,'\t')) return false;
    memcpy(value,response+19,length+1); return true;
}
bool paperos_ime_open(PaperOSIME *ime,const char *helper) {
    ime->input=ime->output=-1; ime->child=0;
    if(!helper || helper[0]!='/' || access(helper,X_OK)) return false;
    int input[2],output[2]; if(pipe(input)) return false;
    if(pipe(output)) { close(input[0]); close(input[1]); return false; }
    for(int i=0;i<2;i++) { fcntl(input[i],F_SETFD,FD_CLOEXEC); fcntl(output[i],F_SETFD,FD_CLOEXEC); }
    ime->child=fork();
    if(!ime->child) { if(dup2(input[0],0)<0 || dup2(output[1],1)<0) _exit(126); close(input[0]); close(input[1]); close(output[0]); close(output[1]); execl(helper,helper,(char*)NULL); _exit(126); }
    close(input[0]); close(output[1]); ime->input=input[1]; ime->output=output[0];
    if(ime->child<0) { paperos_ime_close(ime); return false; }
    char values[16][128]; int count;
    if(!paperos_ime_query(ime,"",values,&count)) { paperos_ime_close(ime); return false; }
    return true;
}

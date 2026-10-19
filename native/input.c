#define _POSIX_C_SOURCE 200809L
#include "input.h"
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define MAGIC 0x50494d31U
static long milliseconds(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec*1000L+t.tv_nsec/1000000L; }
static bool transfer(int fd,void *buffer,size_t size,bool writing,int timeout) {
    long deadline=timeout<0?0:milliseconds()+timeout; size_t done=0;
    while(done<size) {
        int remaining=timeout<0?-1:(int)(deadline-milliseconds());
        if(timeout>=0 && remaining<=0) { errno=ETIMEDOUT; return false; }
        struct pollfd p={fd,writing?POLLOUT:POLLIN,0};
        if(poll(&p,1,remaining)<=0) return false;
        ssize_t n=writing?send(fd,(char*)buffer+done,size-done,MSG_NOSIGNAL|MSG_DONTWAIT):recv(fd,(char*)buffer+done,size-done,MSG_DONTWAIT);
        if(n<0 && (errno==EAGAIN || errno==EWOULDBLOCK)) continue;
        if(n<=0) { if(!n) errno=ECONNRESET; return false; }
        done+=(size_t)n;
    }
    return true;
}
bool paperos_input_utf8(const char *text,bool multiline) {
    const unsigned char *p=(const unsigned char*)text;
    while(*p) {
        uint32_t cp=*p++; unsigned count=0; uint32_t minimum=0;
        if(cp<0x80) { if((cp<32 && !(multiline && (cp=='\n' || cp=='\t'))) || cp==127) return false; continue; }
        if(cp>=0xc2 && cp<=0xdf) { cp&=31; count=1; minimum=0x80; }
        else if(cp>=0xe0 && cp<=0xef) { cp&=15; count=2; minimum=0x800; }
        else if(cp>=0xf0 && cp<=0xf4) { cp&=7; count=3; minimum=0x10000; }
        else return false;
        for(unsigned i=0;i<count;i++) { if((*p&0xc0)!=0x80) return false; cp=(cp<<6)|(*p++&63); }
        if(cp<minimum || cp>0x10ffff || (cp>=0xd800 && cp<=0xdfff)) return false;
    }
    return true;
}
bool paperos_input_valid_request(const PaperOSInputRequest *r) {
    if(r->flags&~7U || !r->max_bytes || r->max_bytes>PAPEROS_INPUT_MAX ||
       (r->flags&PAPEROS_INPUT_PASSWORD && r->flags&PAPEROS_INPUT_MULTILINE) ||
       strnlen(r->title,sizeof(r->title))>PAPEROS_INPUT_TITLE_MAX ||
       strnlen(r->text,sizeof(r->text))>r->max_bytes) return false;
    return paperos_input_utf8(r->title,false) && paperos_input_utf8(r->text,(r->flags&PAPEROS_INPUT_MULTILINE)!=0);
}
bool paperos_input_write_request(int fd,const PaperOSInputRequest *r,int timeout) {
    if(!paperos_input_valid_request(r)) { errno=EINVAL; return false; }
    uint32_t header[5]={htonl(MAGIC),htonl(r->flags),htonl(r->max_bytes),htonl((uint32_t)strlen(r->title)),htonl((uint32_t)strlen(r->text))};
    return transfer(fd,header,sizeof(header),true,timeout) && transfer(fd,(void*)r->title,strlen(r->title),true,timeout) && transfer(fd,(void*)r->text,strlen(r->text),true,timeout);
}
bool paperos_input_read_request(int fd,PaperOSInputRequest *r,int timeout) {
    uint32_t h[5]; memset(r,0,sizeof(*r));
    if(!transfer(fd,h,sizeof(h),false,timeout) || ntohl(h[0])!=MAGIC || ntohl(h[3])>PAPEROS_INPUT_TITLE_MAX || ntohl(h[4])>PAPEROS_INPUT_MAX) return false;
    r->flags=ntohl(h[1]); r->max_bytes=ntohl(h[2]);
    if(!transfer(fd,r->title,ntohl(h[3]),false,timeout) || !transfer(fd,r->text,ntohl(h[4]),false,timeout) ||
       strlen(r->title)!=ntohl(h[3]) || strlen(r->text)!=ntohl(h[4])) return false;
    return paperos_input_valid_request(r);
}
bool paperos_input_write_reply(int fd,const PaperOSInputReply *r,int timeout) {
    size_t length=strnlen(r->text,sizeof(r->text));
    if(r->status>PAPEROS_INPUT_UNAVAILABLE || length>PAPEROS_INPUT_MAX ||
       (r->status!=PAPEROS_INPUT_ACCEPTED && length) || !paperos_input_utf8(r->text,true)) return false;
    uint32_t h[3]={htonl(MAGIC),htonl(r->status),htonl((uint32_t)length)};
    return transfer(fd,h,sizeof(h),true,timeout) && transfer(fd,(void*)r->text,length,true,timeout);
}
bool paperos_input_read_reply(int fd,PaperOSInputReply *r,int timeout) {
    uint32_t h[3]; memset(r,0,sizeof(*r));
    if(!transfer(fd,h,sizeof(h),false,timeout) || ntohl(h[0])!=MAGIC || ntohl(h[1])>PAPEROS_INPUT_UNAVAILABLE || ntohl(h[2])>PAPEROS_INPUT_MAX) return false;
    r->status=ntohl(h[1]);
    if((r->status!=PAPEROS_INPUT_ACCEPTED && ntohl(h[2])) || !transfer(fd,r->text,ntohl(h[2]),false,timeout) || strlen(r->text)!=ntohl(h[2])) return false;
    return paperos_input_utf8(r->text,true);
}
int paperos_input_text(const char *title,const char *initial,unsigned flags,char *result,size_t capacity) {
    if(!title || !initial || !result || capacity<2 || capacity>PAPEROS_INPUT_MAX+1 || strlen(title)>PAPEROS_INPUT_TITLE_MAX || strlen(initial)>=capacity) return PAPEROS_INPUT_FAILED;
    PaperOSInputRequest request={.flags=flags,.max_bytes=(uint32_t)capacity-1};
    memcpy(request.title,title,strlen(title)+1); memcpy(request.text,initial,strlen(initial)+1);
    if(!paperos_input_valid_request(&request)) return PAPEROS_INPUT_FAILED;
    const char *path=getenv("PAPEROS_INPUT_SOCKET"); if(!path) path=PAPEROS_INPUT_SOCKET;
    struct sockaddr_un address={.sun_family=AF_UNIX};
    if(path[0]!='/' || strlen(path)>=sizeof(address.sun_path)) return PAPEROS_INPUT_UNAVAILABLE;
    memcpy(address.sun_path,path,strlen(path)+1);
    int fd=socket(AF_UNIX,SOCK_STREAM,0); if(fd<0) return PAPEROS_INPUT_UNAVAILABLE;
    fcntl(fd,F_SETFD,FD_CLOEXEC);
    if(connect(fd,(struct sockaddr*)&address,sizeof(address))) { close(fd); return PAPEROS_INPUT_UNAVAILABLE; }
    PaperOSInputReply reply;
    bool okay=paperos_input_write_request(fd,&request,2000) && paperos_input_read_reply(fd,&reply,-1);
    close(fd); memset(&request,0,sizeof(request));
    if(!okay) return errno==EINTR?PAPEROS_INPUT_CANCELLED:PAPEROS_INPUT_FAILED;
    if(reply.status==PAPEROS_INPUT_ACCEPTED) {
        if(strlen(reply.text)>=capacity || !paperos_input_utf8(reply.text,(flags&PAPEROS_INPUT_MULTILINE)!=0)) return PAPEROS_INPUT_FAILED;
        memcpy(result,reply.text,strlen(reply.text)+1);
    }
    int status=(int)reply.status; memset(&reply,0,sizeof(reply)); return status;
}

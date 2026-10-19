#define _GNU_SOURCE
#include "input.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop_signal(int value) { (void)value; stopping=1; }
static void end_worker(pid_t worker) {
    if(worker<=0) return;
    for(int n=0;n<20;n++) {
        pid_t result=waitpid(worker,NULL,WNOHANG);
        if(result==worker || (result<0 && errno==ECHILD)) return;
        if(!n) kill(-worker,SIGTERM);
        poll(NULL,0,50);
    }
    kill(-worker,SIGKILL); while(waitpid(worker,NULL,0)<0 && errno==EINTR) {}
}
static pid_t start_worker(const char *ui,int *channel) {
    int pair[2]; if(socketpair(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0,pair)) return -1;
    pid_t child=fork();
    if(!child) {
        if(setsid()<0) _exit(126);
        int copy=fcntl(pair[1],F_DUPFD_CLOEXEC,10);
        int null=open("/dev/null",O_RDWR);
        int log=open("/var/log/paperos-keyboard.log",O_WRONLY|O_CREAT|O_APPEND,0600);
        if(copy<0 || null<0 || dup2(copy,3)<0) _exit(126);
        fcntl(3,F_SETFD,0);
        dup2(null,0); dup2(null,1); dup2(log<0?null:log,2);
        for(int fd=4;fd<256;fd++) close(fd);
        execl(ui,ui,"--input-method","--input-fd","3",(char*)NULL);
        _exit(127);
    }
    close(pair[1]);
    if(child<0) { close(pair[0]); return -1; }
    *channel=pair[0]; return child;
}
static int make_listener(const char *path) {
    struct sockaddr_un address={.sun_family=AF_UNIX};
    if(path[0]!='/' || strlen(path)>=sizeof(address.sun_path)) { errno=EINVAL; return -1; }
    memcpy(address.sun_path,path,strlen(path)+1);
    struct stat old;
    if(!lstat(path,&old)) {
        if(!S_ISSOCK(old.st_mode) || old.st_uid!=geteuid()) { errno=EEXIST; return -1; }
        int probe=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);
        if(probe<0) return -1;
        int active=connect(probe,(struct sockaddr*)&address,sizeof(address));
        int saved=errno; close(probe);
        if(!active) { errno=EADDRINUSE; return -1; }
        if(saved!=ECONNREFUSED) { errno=saved; return -1; }
        if(unlink(path)) return -1;
    } else if(errno!=ENOENT) return -1;
    int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0); if(fd<0) return -1;
    if(bind(fd,(struct sockaddr*)&address,sizeof(address)) || chmod(path,0600) || listen(fd,4)) {
        int saved=errno; close(fd); errno=saved; return -1;
    }
    return fd;
}
int main(int argc,char **argv) {
    const char *path=PAPEROS_INPUT_SOCKET,*ui="/usr/bin/paperos";
    for(int i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--help")) { puts("paperos-inputd [--socket /path] [--ui /path/to/paperos]"); return 0; }
        if(i+1>=argc) return 2;
        if(!strcmp(argv[i],"--socket")) path=argv[++i];
        else if(!strcmp(argv[i],"--ui")) ui=argv[++i]; else return 2;
    }
    if(ui[0]!='/' || access(ui,X_OK)) { fputs("Input UI is unavailable\n",stderr); return 2; }
    umask(077);
    int listener=make_listener(path); if(listener<0) { perror("input socket"); return 2; }
    struct stat owned; if(lstat(path,&owned)) { close(listener); return 2; }
    struct sigaction action={0}; action.sa_handler=stop_signal; sigemptyset(&action.sa_mask);
    sigaction(SIGTERM,&action,NULL); sigaction(SIGINT,&action,NULL); signal(SIGPIPE,SIG_IGN);
    int client=-1,channel=-1; pid_t worker=0;
    while(!stopping) {
        struct pollfd pollers[3]={{listener,POLLIN,0},{client,POLLIN,0},{channel,POLLIN,0}};
        int count=poll(pollers,3,500); if(count<0) { if(errno==EINTR) continue; break; }
        if(client>=0 && pollers[1].revents) {
            char byte; ssize_t n=recv(client,&byte,1,MSG_PEEK|MSG_DONTWAIT);
            if(n==0 || n>0 || (n<0 && errno!=EAGAIN && errno!=EWOULDBLOCK)) {
                close(client); client=-1; end_worker(worker); worker=0;
                if(channel>=0) close(channel);
                channel=-1;
            }
        }
        if(channel>=0 && pollers[2].revents) {
            PaperOSInputReply reply={.status=PAPEROS_INPUT_FAILED};
            if(!paperos_input_read_reply(channel,&reply,2000)) { memset(&reply,0,sizeof(reply)); reply.status=PAPEROS_INPUT_FAILED; }
            /* Release the worker's touch grab before returning focus. */
            end_worker(worker); worker=0;
            close(channel); channel=-1;
            if(client>=0) { paperos_input_write_reply(client,&reply,2000); close(client); client=-1; }
            memset(&reply,0,sizeof(reply));
        }
        if(pollers[0].revents&POLLIN) {
            int next=accept4(listener,NULL,NULL,SOCK_CLOEXEC); if(next<0) continue;
            struct ucred peer; socklen_t peer_size=sizeof(peer);
            PaperOSInputRequest request;
            if(getsockopt(next,SOL_SOCKET,SO_PEERCRED,&peer,&peer_size) || peer.uid!=geteuid() ||
               !paperos_input_read_request(next,&request,2000)) {
                close(next); continue;
            }
            if(client>=0) {
                PaperOSInputReply busy={.status=PAPEROS_INPUT_BUSY};
                paperos_input_write_reply(next,&busy,1000); close(next);
            } else {
                worker=start_worker(ui,&channel);
                if(worker<0 || !paperos_input_write_request(channel,&request,2000)) {
                    end_worker(worker); worker=0;
                    if(channel>=0) close(channel);
                    channel=-1;
                    PaperOSInputReply failed={.status=PAPEROS_INPUT_FAILED}; paperos_input_write_reply(next,&failed,1000); close(next);
                } else client=next;
            }
            memset(&request,0,sizeof(request));
        }
    }
    end_worker(worker);
    if(channel>=0) close(channel);
    if(client>=0) { PaperOSInputReply cancel={.status=PAPEROS_INPUT_CANCELLED}; paperos_input_write_reply(client,&cancel,500); close(client); }
    close(listener);
    struct stat now; if(!lstat(path,&now) && now.st_dev==owned.st_dev && now.st_ino==owned.st_ino) unlink(path);
    return 0;
}

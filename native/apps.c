#define _XOPEN_SOURCE 700
#include "apps.h"
#include "services.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

static int fail(char *error, size_t size, const char *format, ...) {
    va_list args; va_start(args, format); vsnprintf(error, size, format, args); va_end(args); return -1;
}
static bool valid_id(const char *id) {
    size_t length=strlen(id);
    if(!length || length>=64 || id[0]=='.' || strstr(id,"..")) return false;
    for(size_t i=0;i<length;i++) {
        char c=id[i]; if(!((c>='a'&&c<='z') || (c>='0'&&c<='9') || c=='.' || c=='-' || c=='_')) return false;
    }
    return true;
}
static bool valid_relative(const char *path) {
    if(!*path || *path=='/' || strlen(path)>=160) return false;
    const char *part=path;
    while(*part) {
        const char *end=strchr(part,'/'); size_t n=end?(size_t)(end-part):strlen(part);
        if(!n || (n==1&&part[0]=='.') || (n==2&&part[0]=='.'&&part[1]=='.')) return false;
        if(!end) return true;
        part=end+1; if(!*part) return false;
    }
    return false;
}
static int open_program(int directory, const char *path) {
    if(!valid_relative(path)) { errno=EINVAL; return -1; }
    char copy[160]; memcpy(copy,path,strlen(path)+1); int fd=dup(directory);
    char *save=NULL,*part=strtok_r(copy,"/",&save);
    while(part && fd>=0) {
        char *next=strtok_r(NULL,"/",&save);
        int child=openat(fd,part,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|(next?O_DIRECTORY:0)); close(fd); fd=child; part=next;
    }
    struct stat info;
    if(fd>=0 && (fstat(fd,&info) || !S_ISREG(info.st_mode))) { close(fd); errno=EINVAL; return -1; }
    return fd;
}
static int manifest(int directory, PaperOSApp *app) {
    int fd=openat(directory,"manifest.conf",O_RDONLY|O_NOFOLLOW|O_CLOEXEC); if(fd<0) return -1;
    struct stat info; char content[8193];
    if(fstat(fd,&info) || !S_ISREG(info.st_mode) || info.st_size<=0 || info.st_size>8192) { close(fd); errno=EINVAL; return -1; }
    ssize_t length=read(fd,content,(size_t)info.st_size); close(fd);
    if(length!=info.st_size || memchr(content,0,(size_t)length)) { errno=EINVAL; return -1; }
    content[length]=0; memset(app,0,sizeof(*app)); unsigned fields=0;
    char *save=NULL,*line=strtok_r(content,"\n",&save);
    while(line) {
        size_t n=strlen(line); if(n && line[n-1]=='\r') line[--n]=0;
        if(*line && *line!='#') {
            char *value=strchr(line,'='); if(!value) { errno=EINVAL; return -1; } *value++=0;
            char *destination=NULL; size_t capacity=0; unsigned bit=0;
            if(!strcmp(line,"id")) { destination=app->id; capacity=sizeof(app->id); bit=1; }
            else if(!strcmp(line,"name")) { destination=app->name; capacity=sizeof(app->name); bit=2; }
            else if(!strcmp(line,"version")) { destination=app->version; capacity=sizeof(app->version); bit=4; }
            else if(!strcmp(line,"exec")) { destination=app->executable; capacity=sizeof(app->executable); bit=8; }
            else if(!strcmp(line,"description")) { destination=app->description; capacity=sizeof(app->description); bit=16; }
            else if(!strcmp(line,"widget")) { destination=app->widget; capacity=sizeof(app->widget); bit=32; }
            else { errno=EINVAL; return -1; }
            if((fields&bit) || !*value || strlen(value)>=capacity) { errno=EINVAL; return -1; }
            for(const unsigned char *p=(unsigned char*)value;*p;p++) if(*p<32 || *p==127) { errno=EINVAL; return -1; }
            memcpy(destination,value,strlen(value)+1); fields|=bit;
        }
        line=strtok_r(NULL,"\n",&save);
    }
    if((fields&15)!=15 || !valid_id(app->id) || !valid_relative(app->executable)) { errno=EINVAL; return -1; }
    if(app->widget[0] && strcmp(app->widget,"clock") && strcmp(app->widget,"calendar") && strcmp(app->widget,"weather") && strcmp(app->widget,"mihome")) { errno=EINVAL; return -1; }
    fd=open_program(directory,app->executable); if(fd<0) return -1; close(fd); return 0;
}
static int compare(const void *a,const void *b) { return strcmp(((const PaperOSApp*)a)->id,((const PaperOSApp*)b)->id); }
int paperos_apps_scan(const char *root, bool installed, PaperOSApp *apps, int capacity) {
    DIR *dir=opendir(root); if(!dir) return 0; int count=0; struct dirent *item;
    char resolved[PATH_MAX]; if(!realpath(root,resolved)) { closedir(dir); return 0; }
    while((item=readdir(dir)) && count<capacity) {
        if(item->d_name[0]=='.') continue;
        int fd=openat(dirfd(dir),item->d_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC); if(fd<0) continue;
        PaperOSApp candidate; int result=manifest(fd,&candidate); close(fd);
        if(result || (installed && strcmp(candidate.id,item->d_name))) continue;
        if(snprintf(candidate.directory,sizeof(candidate.directory),"%s/%s",resolved,item->d_name)>=(int)sizeof(candidate.directory)) continue;
        apps[count++]=candidate;
    }
    closedir(dir); qsort(apps,(size_t)count,sizeof(*apps),compare); return count;
}
static int root_lock(const char *root, bool exclusive, int *lock) {
    if(mkdir(root,0755) && errno!=EEXIST) return -1;
    int directory=open(root,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC); if(directory<0) return -1;
    *lock=openat(directory,".manager.lock",O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);
    struct stat info;
    if(*lock<0 || fstat(*lock,&info) || !S_ISREG(info.st_mode) || flock(*lock,(exclusive?LOCK_EX:LOCK_SH)|LOCK_NB)) {
        if(*lock>=0) close(*lock);
        *lock=-1; close(directory); return -1;
    }
    return directory;
}
static int remove_tree(int parent,const char *name) {
    int fd=openat(parent,name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC); if(fd<0) return -1;
    DIR *dir=fdopendir(fd); if(!dir) { close(fd); return -1; } struct dirent *item; int result=0;
    while((item=readdir(dir))) {
        if(!strcmp(item->d_name,".") || !strcmp(item->d_name,"..")) continue;
        struct stat info;
        if(fstatat(fd,item->d_name,&info,AT_SYMLINK_NOFOLLOW)) { result=-1; break; }
        if(S_ISDIR(info.st_mode)) result=remove_tree(fd,item->d_name); else result=unlinkat(fd,item->d_name,0);
        if(result) break;
    }
    closedir(dir); if(!result) result=unlinkat(parent,name,AT_REMOVEDIR); return result;
}
static int copy_tree(int source,int destination,int depth,unsigned *files,size_t *bytes) {
    if(depth>8) { errno=EFBIG; return -1; }
    DIR *dir=fdopendir(dup(source)); if(!dir) return -1; struct dirent *item; int result=0;
    while((item=readdir(dir))) {
        if(!strcmp(item->d_name,".") || !strcmp(item->d_name,"..")) continue;
        if(++*files>256) { errno=EFBIG; result=-1; break; }
        struct stat info; if(fstatat(source,item->d_name,&info,AT_SYMLINK_NOFOLLOW)) { result=-1; break; }
        if(S_ISDIR(info.st_mode)) {
            if(mkdirat(destination,item->d_name,0755)) { result=-1; break; }
            int a=openat(source,item->d_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
            int b=openat(destination,item->d_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
            result=(a<0 || b<0)?-1:copy_tree(a,b,depth+1,files,bytes);
            if(a>=0) close(a);
            if(b>=0) { if(!result) result=fsync(b); close(b); }
        } else if(S_ISREG(info.st_mode)) {
            int a=openat(source,item->d_name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
            int b=openat(destination,item->d_name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,(info.st_mode&0111)?0755:0644);
            struct stat opened;
            if(a<0 || b<0 || fstat(a,&opened) || !S_ISREG(opened.st_mode)) result=-1;
            else {
                char buffer[32768]; ssize_t n;
                while((n=read(a,buffer,sizeof(buffer)))>0) {
                    *bytes+=(size_t)n; if(*bytes>64*1024*1024) { errno=EFBIG; result=-1; break; }
                    ssize_t written=0; while(written<n) { ssize_t part=write(b,buffer+written,(size_t)(n-written)); if(part<=0) { result=-1; break; } written+=part; }
                    if(result) break;
                }
                if(n<0 || fsync(b)) result=-1;
            }
            if(a>=0) close(a);
            if(b>=0) close(b);
        } else { errno=EINVAL; result=-1; }
        if(result) break;
    }
    closedir(dir); return result;
}
int paperos_app_install(const char *root,const char *package,char *error,size_t size) {
    int source=open(package,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC); PaperOSApp app;
    if(source<0 || manifest(source,&app)) { if(source>=0) close(source); return fail(error,size,"应用包格式无效"); }
    int lock=-1,directory=root_lock(root,true,&lock);
    if(directory<0) { close(source); return fail(error,size,"应用库忙碌或不可写"); }
    char stage[1024],old[1024],*stage_name=NULL,*old_name=NULL; int result=-1; bool displaced=false;
    if(snprintf(stage,sizeof(stage),"%s/.install-XXXXXX",root)>=(int)sizeof(stage) || !mkdtemp(stage)) goto finish;
    stage_name=strrchr(stage,'/')+1;
    int target=openat(directory,stage_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    unsigned files=0; size_t bytes=0;
    if(target<0) goto finish;
    result=copy_tree(source,target,0,&files,&bytes);
    if(!result) {
        PaperOSApp copied; result=manifest(target,&copied);
        if(!result && memcmp(&copied,&app,sizeof(app))) { errno=EINVAL; result=-1; }
        int executable=(!result)?open_program(target,app.executable):-1;
        if(executable>=0) { result=fchmod(executable,0755); close(executable); }
        else result=-1;
        if(!result) result=fchmod(target,0755);
        if(!result) result=fsync(target);
    }
    close(target); if(result) goto finish;
    struct stat existing;
    if(!fstatat(directory,app.id,&existing,AT_SYMLINK_NOFOLLOW)) {
        int prior=openat(directory,app.id,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC); PaperOSApp previous;
        if(prior<0) { result=-1; goto finish; }
        result=manifest(prior,&previous); close(prior);
        if(result || strcmp(previous.id,app.id)) { result=-1; goto finish; }
        if(snprintf(old,sizeof(old),"%s/.previous-XXXXXX",root)>=(int)sizeof(old) || !mkdtemp(old)) { result=-1; goto finish; }
        old_name=strrchr(old,'/')+1;
        if(unlinkat(directory,old_name,AT_REMOVEDIR) || renameat(directory,app.id,directory,old_name)) { result=-1; goto finish; }
        displaced=true;
    } else if(errno!=ENOENT) { result=-1; goto finish; }
    result=renameat(directory,stage_name,directory,app.id);
    if(result && displaced) { renameat(directory,old_name,directory,app.id); displaced=false; }
    if(!result) { stage_name=NULL; fsync(directory); }
finish:
    if(stage_name) remove_tree(directory,stage_name);
    if(displaced && !result) remove_tree(directory,old_name);
    close(source); close(directory); close(lock);
    if(result) return fail(error,size,"安装失败，原应用已保留");
    snprintf(error,size,"%s 已安装",app.name); return 0;
}
int paperos_app_remove(const char *root,const char *id,char *error,size_t size) {
    if(!valid_id(id)) return fail(error,size,"应用编号无效");
    int lock=-1,directory=root_lock(root,true,&lock); if(directory<0) return fail(error,size,"应用正在运行或应用库不可写");
    int fd=openat(directory,id,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC); PaperOSApp app;
    int result=(fd>=0)?manifest(fd,&app):-1; if(fd>=0) close(fd);
    if(!result && strcmp(app.id,id)) result=-1;
    if(!result) result=remove_tree(directory,id);
    if(!result) fsync(directory);
    close(directory); close(lock);
    if(result) return fail(error,size,"卸载失败");
    if(!strcmp(id,"org.paperos.alarm")) { char message[256]; paperos_service_command("alarm-disarm",NULL,message,sizeof(message)); }
    snprintf(error,size,"应用已卸载，应用数据保留"); return 0;
}
pid_t paperos_app_start(const char *root,const PaperOSApp *app,const char *launcher,
                       const char *font,int *lock,char *error,size_t size) {
    if(!valid_id(app->id)) return fail(error,size,"应用编号无效");
    int directory=root_lock(root,true,lock); if(directory<0) return fail(error,size,"另一个应用正在运行或应用库忙碌");
    int fd=openat(directory,app->id,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC); PaperOSApp current;
    int result=fd>=0?manifest(fd,&current):-1;
    if(fd>=0) close(fd);
    if(result || strcmp(current.id,app->id)) { close(directory); close(*lock); *lock=-1; return fail(error,size,"应用不可启动"); }
    char resolved[PATH_MAX],program[1024],data[1024],appdir[1024];
    if(!realpath(root,resolved) || snprintf(appdir,sizeof(appdir),"%s/%s",resolved,app->id)>=(int)sizeof(appdir) ||
       snprintf(program,sizeof(program),"%s/%s",appdir,current.executable)>=(int)sizeof(program)) {
        close(directory); close(*lock); *lock=-1; return fail(error,size,"应用路径过长");
    }
    if(mkdirat(directory,".data",0700) && errno!=EEXIST) result=-1;
    int data_root=openat(directory,".data",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(data_root<0 || (mkdirat(data_root,app->id,0700) && errno!=EEXIST)) result=-1;
    int data_fd=data_root<0?-1:openat(data_root,app->id,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(data_fd<0) result=-1; else close(data_fd);
    if(data_root>=0) close(data_root);
    if(snprintf(data,sizeof(data),"%s/.data/%s",resolved,app->id)>=(int)sizeof(data)) result=-1;
    close(directory);
    if(result) { close(*lock); *lock=-1; return fail(error,size,"无法创建应用数据目录"); }
    pid_t child=fork();
    if(!child) {
        if(setsid()<0 || chdir(appdir)) _exit(126);
        setenv("PAPEROS_APP_ID",app->id,1); setenv("PAPEROS_APP_DIR",appdir,1);
        setenv("PAPEROS_DATA_DIR",data,1); setenv("PAPEROS_LAUNCHER",launcher,1);
        if(font) setenv("PAPEROS_FONT",font,1);
        execl(program,program,(char*)NULL); perror(program); _exit(126);
    }
    if(child<0) { close(*lock); *lock=-1; return fail(error,size,"无法启动应用"); }
    return child;
}

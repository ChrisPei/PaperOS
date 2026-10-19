#define _GNU_SOURCE
/* PID 1 bootstrap for KT3. Retains stock init as the failure path.
 * The existing p4 FAT filesystem and a provisioned ext3 image are accessed
 * through loop devices. No raw write targets eMMC, IDME or boot regions.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/loop.h>
#include <mntent.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define CONTROL "/mnt/paperos-boot"
#define NEWROOT "/mnt/paperos-root"
#define STOCK "/sbin/init.paperos-stock"
#define TOKEN "paperos-boot-v1\n"
static int log_fd=-1, fat_loop=-1, root_loop=-1, part_fd=-1, image_fd=-1;
static int fat_mounted, root_mounted, control_moved, pivoted;
static int moved[4];
static const char *const virtuals[]={"/proc","/sys","/dev"};
static char **original_argv;

static void log_line(const char *format, ...) {
    char line[512];
    va_list ap;
    va_start(ap,format); vsnprintf(line,sizeof(line),format,ap); va_end(ap);
    dprintf(2,"PaperOS bootstrap: %s\n",line);
    if(log_fd>=0) { dprintf(log_fd,"%s\n",line); fsync(log_fd); }
}

static void stock(void) {
    if(pivoted) {
        log_line("New init failed; boot request is cleared. Rebooting to stock.");
        sync(); reboot(RB_AUTOBOOT);
        for(;;) pause();
    }
    if(chdir("/")) log_line("Cannot return to stock root directory: %s",strerror(errno));
    for(int i=2;i>=0;i--) if(moved[i]) {
        char path[128]; snprintf(path,sizeof(path),NEWROOT"%s",virtuals[i]);
        if(mount(path,virtuals[i],NULL,MS_MOVE,NULL)) log_line("Cannot restore %s",virtuals[i]);
    }
    if(control_moved && !mount(NEWROOT"/boot/paperos-control",CONTROL,NULL,MS_MOVE,NULL))
        fat_mounted=1;
    if(root_mounted) umount(NEWROOT);
    if(root_loop>=0) { close(root_loop); root_loop=-1; }
    if(image_fd>=0) { close(image_fd); image_fd=-1; }
    if(log_fd>=0) close(log_fd);
    if(fat_mounted) umount(CONTROL);
    if(fat_loop>=0) close(fat_loop);
    if(part_fd>=0) close(part_fd);
    execv(STOCK,original_argv);
    dprintf(2,"PaperOS: cannot execute retained stock init: %s\n",strerror(errno));
    sync(); reboot(RB_AUTOBOOT);
    for(;;) pause();
}

static void fail(const char *what) {
    int saved=errno;
    log_line("%s: %s; returning to stock init",what,strerror(saved));
    stock();
}

static int loop_node(int n, char *path, size_t size) {
    struct stat st;
    snprintf(path,size,"/dev/loop%d",n);
    if(lstat(path,&st)) {
        if(errno!=ENOENT || mknod(path,S_IFBLK|0600,makedev(7,n))) return -1;
    } else if(!S_ISBLK(st.st_mode) || st.st_rdev!=makedev(7,n)) {
        errno=EINVAL; return -1;
    }
    return open(path,O_RDWR|O_CLOEXEC);
}

static int attach_loop(int backing, unsigned long long offset, int reuse,
                       char *path, size_t size) {
    struct stat backing_stat;
    if(fstat(backing,&backing_stat)) return -1;
    /* Reuse the initramfs userstore mapping when it already exists. */
    if(reuse) for(int n=0;n<16;n++) {
        int fd=loop_node(n,path,size);
        struct loop_info64 info;
        if(fd<0) continue;
        memset(&info,0,sizeof(info));
        if(!ioctl(fd,LOOP_GET_STATUS64,&info) && info.lo_offset==offset &&
           info.lo_rdevice==(unsigned long long)backing_stat.st_rdev) return fd;
        close(fd);
    }
    for(int n=0;n<16;n++) {
        int fd=loop_node(n,path,size);
        struct loop_info64 info;
        if(fd<0) continue;
        memset(&info,0,sizeof(info));
        if(!ioctl(fd,LOOP_GET_STATUS64,&info) || errno!=ENXIO) { close(fd); continue; }
        if(ioctl(fd,LOOP_SET_FD,backing)) { close(fd); continue; }
        info.lo_offset=offset; info.lo_flags=LO_FLAGS_AUTOCLEAR;
        if(ioctl(fd,LOOP_SET_STATUS64,&info)) {
            int saved=errno; ioctl(fd,LOOP_CLR_FD,0); close(fd); errno=saved; return -1;
        }
        return fd;
    }
    errno=ENOSPC; return -1;
}

static int existing_mount(const char *device, char *out, size_t size) {
    struct stat wanted,current;
    if(stat(device,&wanted)) return 0;
    FILE *file=setmntent("/proc/mounts","r");
    if(!file) return 0;
    struct mntent *row;
    int found=0;
    while((row=getmntent(file))) {
        if(!strcmp(row->mnt_type,"vfat") && !stat(row->mnt_fsname,&current) &&
           current.st_rdev==wanted.st_rdev && S_ISBLK(current.st_mode)) {
            snprintf(out,size,"%s",row->mnt_dir); found=1; break;
        }
    }
    endmntent(file); return found;
}

static int exact_token(const char *path) {
    char token[64]={0};
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0) return 0;
    ssize_t n=read(fd,token,sizeof(token)-1); close(fd);
    return n==(ssize_t)strlen(TOKEN) && !memcmp(token,TOKEN,strlen(TOKEN));
}

int main(int argc,char **argv) {
    if(argc==2 && !strcmp(argv[1],"--check")) {
        puts("paperos-bootstrap-v1"); return 0;
    }
    if(getpid()!=1) { fputs("PaperOS bootstrap is restricted to PID 1.\n",stderr); return 1; }
    original_argv=argv;
    if(access("/proc/1",F_OK)) {
        if(mount("proc","/proc","proc",0,NULL)) fail("mount proc");
    }
    if(access("/sys/class",F_OK)) mount("sysfs","/sys","sysfs",0,NULL);
    if(access("/dev/mmcblk0p4",F_OK) &&
       mount("devtmpfs","/dev","devtmpfs",MS_NOSUID,"mode=0755"))
        fail("mount early device filesystem");
    char fat_device[64],root_device[64],previous[256];
    part_fd=open("/dev/mmcblk0p4",O_RDWR|O_CLOEXEC);
    if(part_fd<0) fail("open userstore partition");
    fat_loop=attach_loop(part_fd,8192,1,fat_device,sizeof(fat_device));
    if(fat_loop<0) fail("map userstore");
    if(existing_mount(fat_device,previous,sizeof(previous))) {
        if(mount(previous,CONTROL,NULL,MS_BIND,NULL)) fail("bind userstore");
    } else if(mount(fat_device,CONTROL,"vfat",MS_NOSUID|MS_NODEV|MS_NOEXEC,
                   "utf8,uid=0,gid=0,umask=0077")) fail("mount userstore");
    fat_mounted=1;
    if(!exact_token(CONTROL"/paperos/boot.enable")) stock();
    log_fd=open(CONTROL"/paperos/boot.log",O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC,0600);
    log_line("Boot request found; clearing it before starting the independent OS");
    if(unlink(CONTROL"/paperos/boot.enable")) fail("clear boot request");
    sync();
    image_fd=open(CONTROL"/paperos/system.ext3",O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    if(image_fd<0) fail("open independent filesystem");
    struct stat image_stat;
    unsigned char sb[136];
    if(fstat(image_fd,&image_stat) || !S_ISREG(image_stat.st_mode) ||
       image_stat.st_size<64*1024*1024 || image_stat.st_size>1024LL*1024*1024 ||
       pread(image_fd,sb,sizeof(sb),1024)!=(ssize_t)sizeof(sb) ||
       sb[56]!=0x53 || sb[57]!=0xef || memcmp(sb+120,"paperos-root",12)) {
        errno=EINVAL; fail("validate independent filesystem");
    }
    if(flock(image_fd,LOCK_EX|LOCK_NB)) fail("lock independent filesystem");
    root_loop=attach_loop(image_fd,0,0,root_device,sizeof(root_device));
    if(root_loop<0) fail("map independent filesystem");
    if(mount(root_device,NEWROOT,"ext3",MS_NOATIME,NULL)) fail("mount independent filesystem");
    root_mounted=1;
    if(access(NEWROOT"/sbin/init",X_OK) || access(NEWROOT"/etc/paperos-release",R_OK))
        fail("validate independent init");
    if(mkdir(NEWROOT"/old-root",0755) && errno!=EEXIST) fail("prepare old root directory");
    if(mount(CONTROL,NEWROOT"/boot/paperos-control",NULL,MS_MOVE,NULL)) fail("move userstore");
    fat_mounted=0; control_moved=1;
    for(int i=0;i<3;i++) {
        char target[128]; snprintf(target,sizeof(target),NEWROOT"%s",virtuals[i]);
        if(mount(virtuals[i],target,NULL,MS_MOVE,NULL)) fail("move virtual filesystem");
        moved[i]=1;
    }
    log_line("Switching PID 1 to the independent root filesystem on %s",root_device);
    if(chdir(NEWROOT) || syscall(SYS_pivot_root,".","old-root")) fail("pivot root");
    pivoted=1;
    if(chdir("/")) fail("enter independent root");
    int console_fd=open("/dev/console",O_RDWR|O_NOCTTY|O_CLOEXEC);
    if(console_fd>=0) {
        for(int fd=0;fd<3;fd++) if(dup2(console_fd,fd)<0) fail("reopen console");
        if(console_fd>2) close(console_fd);
    }
    if(umount2("/old-root",MNT_DETACH)) log_line("Stock root detach: %s",strerror(errno));
    if(log_fd>=0) close(log_fd);
    log_fd=-1;
    /* No file descriptors or mappings from the stock system remain after exec. */
    for(int fd=3;fd<256;fd++) close(fd);
    char *const init_argv[]={"/sbin/init",NULL};
    execv(init_argv[0],init_argv);
    fail("execute independent init");
    return 1;
}

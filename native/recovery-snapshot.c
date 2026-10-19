#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <linux/magic.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/sysmacros.h>
#include <time.h>
#include <unistd.h>

/* Snapshot the two probed 64 MiB ext3 partitions into RAM. No block writes. */
static volatile sig_atomic_t interrupted;
static void on_signal(int sig) { interrupted = sig; }

static unsigned long memory_kib(const char *wanted) {
    FILE *file = fopen("/proc/meminfo", "r");
    char line[160], key[80];
    unsigned long value, found = 0;
    if (!file) return 0;
    while (fgets(line, sizeof(line), file)) {
        if (sscanf(line, "%79[^:]: %lu", key, &value) == 2 && !strcmp(key, wanted)) {
            found = value;
            break;
        }
    }
    fclose(file);
    return found;
}

int main(int argc, char **argv) {
    const uint64_t expected = UINT64_C(67108864);
    const size_t chunk = 1048576;
    int slot, block = -1, mountfd = -1, output = -1;
    int frozen = 0, created = 0, result = 1, saved_errno = 0;
    const char *device, *mountpoint;
    char final[128], temporary[128];
    void *buffer = NULL;
    struct stat st;
    struct statfs fs;
    struct sigaction action;
    struct timespec start = {0}, end = {0};
    uint64_t size = 0, copied = 0;
    if (argc != 3 || strcmp(argv[1], "--slot") ||
        (strcmp(argv[2], "2") && strcmp(argv[2], "3"))) {
        fputs("Usage: paperos-snapshot --slot 2|3\n", stderr);
        return 2;
    }
    slot = argv[2][0] - '0';
    device = slot == 2 ? "/dev/mmcblk0p2" : "/dev/mmcblk0p3";
    mountpoint = slot == 2 ? "/usr/share/nh" : "/var/local";
    snprintf(final, sizeof(final), "/dev/shm/paperos-snapshot/p%d.img", slot);
    snprintf(temporary, sizeof(temporary), "/dev/shm/paperos-snapshot/p%d.img.tmp", slot);
    if (geteuid() != 0) { fputs("Root is required\n", stderr); return 2; }
    if (statfs("/dev/shm/paperos-snapshot", &fs) || fs.f_type != TMPFS_MAGIC) {
        fputs("Snapshot destination must be the prepared RAM directory\n", stderr);
        return 2;
    }
    long long available = (long long)memory_kib("MemFree") + memory_kib("Buffers") +
        memory_kib("Cached") + memory_kib("SReclaimable") - memory_kib("Shmem");
    if (available < 98304) { fputs("Not enough available RAM for a safe snapshot\n", stderr); return 2; }
    block = open(device, O_RDONLY | O_DIRECT | O_CLOEXEC | O_NOFOLLOW);
    if (block < 0 || fstat(block, &st) || !S_ISBLK(st.st_mode) ||
        major(st.st_rdev) != 179 || minor(st.st_rdev) != (unsigned)slot ||
        ioctl(block, BLKGETSIZE64, &size) || size != expected) {
        fputs("Source is not the probed read-only 64 MiB eMMC partition\n", stderr);
        goto cleanup;
    }
    mountfd = open(mountpoint, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (mountfd < 0 || fstat(mountfd, &st) || st.st_dev != makedev(179, slot) ||
        fstatfs(mountfd, &fs) || fs.f_type != EXT2_SUPER_MAGIC) {
        fputs("Expected ext3 mount does not match source block device\n", stderr);
        goto cleanup;
    }
    if (access(final, F_OK) == 0 || posix_memalign(&buffer, 4096, chunk)) {
        fputs("RAM snapshot already exists or buffer allocation failed\n", stderr);
        goto cleanup;
    }
    output = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (output < 0) goto cleanup;
    created = 1;
    memset(&action, 0, sizeof(action));
    action.sa_handler = on_signal;
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGALRM, &action, NULL);
    alarm(30);
    clock_gettime(CLOCK_MONOTONIC, &start);
    if (ioctl(mountfd, FIFREEZE, 0) < 0) goto cleanup;
    frozen = 1;
    while (copied < expected && !interrupted) {
        ssize_t count = read(block, buffer, chunk);
        if (count < 0 && errno == EINTR && !interrupted) continue;
        if (count <= 0) goto cleanup;
        size_t done = 0;
        while (done < (size_t)count && !interrupted) {
            ssize_t written = write(output, (char *)buffer + done, count - done);
            if (written < 0 && errno == EINTR && !interrupted) continue;
            if (written <= 0) goto cleanup;
            done += (size_t)written;
        }
        if (done != (size_t)count) goto cleanup;
        copied += (uint64_t)count;
    }
    if (copied != expected || interrupted) goto cleanup;
    if (ioctl(mountfd, FITHAW, 0) < 0) goto cleanup;
    frozen = 0;
    clock_gettime(CLOCK_MONOTONIC, &end);
    alarm(0);
    if (fsync(output)) goto cleanup;
    if (close(output)) { output = -1; goto cleanup; }
    output = -1;
    if (rename(temporary, final)) goto cleanup;
    created = 0;
    result = 0;
    printf("{\"slot\":%d,\"bytes\":%llu,\"frozen_seconds\":%.3f}\n", slot,
        (unsigned long long)copied,
        (double)(end.tv_sec - start.tv_sec) + (end.tv_nsec - start.tv_nsec) / 1e9);
cleanup:
    saved_errno = errno;
    if (frozen && ioctl(mountfd, FITHAW, 0) < 0) {
        fputs("Could not thaw filesystem; reboot is required\n", stderr);
        result = 3;
    }
    alarm(0);
    if (output >= 0) close(output);
    if (mountfd >= 0) close(mountfd);
    if (block >= 0) close(block);
    if (created) unlink(temporary);
    free(buffer);
    if (result) fprintf(stderr, "Snapshot failed: %s; signal=%d\n", strerror(saved_errno), (int)interrupted);
    return result;
}

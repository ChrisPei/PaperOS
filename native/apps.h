#ifndef PAPEROS_APPS_H
#define PAPEROS_APPS_H
#include <stdbool.h>
#include <stddef.h>
#include <sys/types.h>
#define PAPEROS_MAX_APPS 32
typedef struct {
    char id[64], name[128], version[32], executable[160], description[256];
    char directory[768];
    char widget[24];
} PaperOSApp;
int paperos_apps_scan(const char *root, bool installed, PaperOSApp *apps, int capacity);
int paperos_app_install(const char *root, const char *package, char *error, size_t size);
int paperos_app_remove(const char *root, const char *id, char *error, size_t size);
pid_t paperos_app_start(const char *root, const PaperOSApp *app, const char *launcher,
                       const char *font, int *lock, char *error, size_t size);
#endif

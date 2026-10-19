#ifndef PAPEROS_STORE_H
#define PAPEROS_STORE_H
#include <stdbool.h>
#define PAPEROS_STORE_MAX 1024
typedef struct {
    char key[96],id[64],name[128],version[64],installed[64],kind[24],source[128],size[32];
    char reason[256],description[512],url[768],sha256[65],source_id[64]; bool update;
} PaperOSStoreEntry;
typedef struct { char id[64],name[128],url[768],format[32],error[384]; bool enabled; } PaperOSStoreSource;
typedef struct { PaperOSStoreEntry entries[PAPEROS_STORE_MAX]; int count; PaperOSStoreSource sources[8],presets[8]; int source_count,preset_count; unsigned long revision; bool available; } PaperOSStoreCatalog;
typedef struct { PaperOSStoreCatalog catalog; int tab,page,source_page; char selected[96],query[128],source_selected[64],filter_source[64]; bool confirm_remove,confirm_source_remove,show_incompatible; } PaperOSStoreUI;
bool paperos_store_read(PaperOSStoreCatalog *catalog,const char *path,unsigned long revision);
#endif

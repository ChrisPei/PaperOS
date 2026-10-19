#include "store.h"
#include <string.h>

static int compare_name(const char *left,const char *right){
    const unsigned char *a=(const unsigned char*)left,*b=(const unsigned char*)right;
    while(*a||*b){unsigned x=*a,y=*b;if(x>='A'&&x<='Z')x+=32;if(y>='A'&&y<='Z')y+=32;if(x!=y)return x<y?-1:1;if(!*a)break;a++;b++;}
    return 0;
}
int paperos_store_compare(const PaperOSStoreEntry *a,const PaperOSStoreEntry *b,int mode){
    if(mode==0&&a->stars!=b->stars)return a->stars>b->stars?-1:1;
    if(mode!=2){int date=strcmp(a->updated,b->updated);if(date)return date>0?-1:1;}
    int name=compare_name(a->name,b->name);if(name)return name;
    return strcmp(a->key,b->key);
}

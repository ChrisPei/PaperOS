#define _POSIX_C_SOURCE 200809L
#include "input.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc,char **argv) {
    const char *title="输入文字",*source=NULL,*output=NULL;
    unsigned flags=0; size_t capacity=PAPEROS_INPUT_MAX+1;
    for(int i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--help")) { puts("paperos-input [--title LABEL] [--text-file FILE] [--output FILE]\n              [--multiline | --password] [--english] [--max-bytes 1..8191]\nWithout --output, accepted UTF-8 is written to stdout. Cancel exits 1 without changing output."); return 0; }
        if(!strcmp(argv[i],"--multiline")) { flags|=PAPEROS_INPUT_MULTILINE; continue; }
        if(!strcmp(argv[i],"--password")) { flags|=PAPEROS_INPUT_PASSWORD; continue; }
        if(!strcmp(argv[i],"--english")) { flags|=PAPEROS_INPUT_ENGLISH; continue; }
        if(i+1>=argc) return 2;
        if(!strcmp(argv[i],"--title")) title=argv[++i];
        else if(!strcmp(argv[i],"--text-file")) source=argv[++i];
        else if(!strcmp(argv[i],"--output")) output=argv[++i];
        else if(!strcmp(argv[i],"--max-bytes")) { char *end; errno=0; unsigned long n=strtoul(argv[++i],&end,10); if(errno || !*argv[i] || *end || n<1 || n>PAPEROS_INPUT_MAX) return 2; capacity=n+1; }
        else return 2;
    }
    char text[PAPEROS_INPUT_MAX+1]={0};
    if(source) {
        FILE *file=fopen(source,"rb");
        if(file) { size_t n=fread(text,1,capacity-1,file); if(ferror(file) || fgetc(file)!=EOF || memchr(text,0,n)) { fclose(file); return 2; } fclose(file); }
        else if(errno!=ENOENT) { perror("initial text"); return 2; }
    }
    int status=paperos_input_text(title,text,flags,text,capacity);
    if(status!=PAPEROS_INPUT_ACCEPTED) { memset(text,0,sizeof(text)); return status==PAPEROS_INPUT_CANCELLED?1:2; }
    size_t length=strlen(text);
    if(!output) { bool okay=fwrite(text,1,length,stdout)==length; memset(text,0,sizeof(text)); return okay?0:2; }
    if(strlen(output)>4000) return 2;
    char temporary[4096]; snprintf(temporary,sizeof(temporary),"%s.input-XXXXXX",output);
    int fd=mkstemp(temporary); if(fd<0) { perror("output"); return 2; }
    size_t done=0; bool okay=true;
    while(done<length) { ssize_t n=write(fd,text+done,length-done); if(n<0 && errno==EINTR) continue; if(n<=0) { okay=false; break; } done+=(size_t)n; }
    memset(text,0,sizeof(text));
    if(fsync(fd)) okay=false;
    if(close(fd)) okay=false;
    if(!okay || rename(temporary,output)) { unlink(temporary); return 2; }
    return 0;
}

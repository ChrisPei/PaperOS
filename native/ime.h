#ifndef PAPEROS_IME_H
#define PAPEROS_IME_H
#include <stdbool.h>
#include <sys/types.h>
typedef struct { int input,output; pid_t child; } PaperOSIME;
bool paperos_ime_open(PaperOSIME *ime,const char *helper);
bool paperos_ime_query(PaperOSIME *ime,const char *text,char values[16][128],int *count);
bool paperos_ime_commit(PaperOSIME *ime,int index,char value[128]);
void paperos_ime_close(PaperOSIME *ime);
#endif

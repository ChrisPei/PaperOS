#ifndef PAPEROS_KEYBOARD_H
#define PAPEROS_KEYBOARD_H
#include "input.h"
#include "ime.h"
enum { PAPEROS_KB_CHINESE, PAPEROS_KB_LOWER, PAPEROS_KB_UPPER, PAPEROS_KB_NUMBERS, PAPEROS_KB_SYMBOLS };
/* KT3 portrait keymap: 38px candidates + 237px keys. */
#define PAPEROS_KB_TOP 525
#define PAPEROS_KB_GRID_TOP 563
enum { PAPEROS_KEY_CANCEL, PAPEROS_KEY_DONE, PAPEROS_KEY_LEFT, PAPEROS_KEY_RIGHT,
       PAPEROS_KEY_SHIFT, PAPEROS_KEY_BACKSPACE, PAPEROS_KEY_LAYOUT,
       PAPEROS_KEY_LANGUAGE, PAPEROS_KEY_DOT, PAPEROS_KEY_SPACE,
       PAPEROS_KEY_COMMA, PAPEROS_KEY_PERIOD, PAPEROS_KEY_ENTER,
       PAPEROS_KEY_MORE, PAPEROS_KEY_COUNT };
typedef struct {
    PaperOSInputRequest request;
    PaperOSIME engine;
    size_t cursor;
    int mode, alpha_mode, symbols_page, candidate_count, candidate_page, status;
    char preedit[33], candidates[16][128], message[128];
} PaperOSKeyboard;
void paperos_keyboard_open(PaperOSKeyboard *keyboard,const PaperOSInputRequest *request,const char *helper);
void paperos_keyboard_close(PaperOSKeyboard *keyboard);
bool paperos_keyboard_insert(PaperOSKeyboard *keyboard,const char *text);
bool paperos_keyboard_commit(PaperOSKeyboard *keyboard,int index);
void paperos_keyboard_backspace(PaperOSKeyboard *keyboard);
void paperos_keyboard_move(PaperOSKeyboard *keyboard,int direction);
void paperos_keyboard_mode(PaperOSKeyboard *keyboard,int mode,const char *helper);
const char *paperos_keyboard_keys(const PaperOSKeyboard *keyboard);
bool paperos_keyboard_key(const PaperOSKeyboard *keyboard,int index,int *x,int *y,int *w,int *h);
bool paperos_keyboard_control(int control,int *x,int *y,int *w,int *h);
const char *paperos_keyboard_label(const PaperOSKeyboard *keyboard,int control);
void paperos_keyboard_tap(PaperOSKeyboard *keyboard,int x,int y,const char *helper);
#endif

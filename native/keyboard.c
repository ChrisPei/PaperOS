#include "keyboard.h"
#include <stdio.h>
#include <string.h>

static void message(PaperOSKeyboard *k,const char *value) { snprintf(k->message,sizeof(k->message),"%s",value); }
static void query(PaperOSKeyboard *k) {
    k->candidate_count=0; k->candidate_page=0;
    if(!paperos_ime_query(&k->engine,k->preedit,k->candidates,&k->candidate_count)) {
        paperos_ime_close(&k->engine); k->mode=k->alpha_mode=PAPEROS_KB_LOWER;
        message(k,"中文引擎暂不可用，拼音仍保留");
    }
}
void paperos_keyboard_open(PaperOSKeyboard *k,const PaperOSInputRequest *r,const char *helper) {
    memset(k,0,sizeof(*k)); k->request=*r; k->cursor=strlen(r->text); k->status=-1;
    k->engine.input=k->engine.output=-1;
    k->mode=k->alpha_mode=PAPEROS_KB_LOWER;
    if(!(r->flags&(PAPEROS_INPUT_PASSWORD|PAPEROS_INPUT_ENGLISH))) paperos_keyboard_mode(k,PAPEROS_KB_CHINESE,helper);
}
void paperos_keyboard_close(PaperOSKeyboard *k) { paperos_ime_close(&k->engine); memset(k,0,sizeof(*k)); k->engine.input=k->engine.output=-1; }
bool paperos_keyboard_insert(PaperOSKeyboard *k,const char *value) {
    size_t n=strlen(value),length=strlen(k->request.text);
    if(!paperos_input_utf8(value,(k->request.flags&PAPEROS_INPUT_MULTILINE)!=0)) return false;
    if(length+n>k->request.max_bytes) { message(k,"输入内容已达上限"); return false; }
    memmove(k->request.text+k->cursor+n,k->request.text+k->cursor,length-k->cursor+1);
    memcpy(k->request.text+k->cursor,value,n); k->cursor+=n; k->message[0]=0; return true;
}
bool paperos_keyboard_commit(PaperOSKeyboard *k,int index) {
    if(!k->preedit[0]) return true;
    char value[128];
    if(index>=0 && index<k->candidate_count) {
        if(strlen(k->request.text)+strlen(k->candidates[index])>k->request.max_bytes) { message(k,"输入内容已达上限"); return false; }
        if(!paperos_ime_commit(&k->engine,index,value)) { message(k,"候选词提交失败，拼音仍保留"); return false; }
    } else snprintf(value,sizeof(value),"%s",k->preedit);
    if(!paperos_keyboard_insert(k,value)) { if(k->engine.child>0) query(k); return false; }
    k->preedit[0]=0; k->candidate_count=0; return true;
}
void paperos_keyboard_backspace(PaperOSKeyboard *k) {
    size_t pending=strlen(k->preedit);
    if(pending) { k->preedit[pending-1]=0; if(k->engine.child>0) query(k); return; }
    if(!k->cursor) return;
    size_t previous=k->cursor-1;
    while(previous && ((unsigned char)k->request.text[previous]&0xc0)==0x80) previous--;
    memmove(k->request.text+previous,k->request.text+k->cursor,strlen(k->request.text+k->cursor)+1);
    k->cursor=previous; k->message[0]=0;
}
void paperos_keyboard_move(PaperOSKeyboard *k,int direction) {
    if(!paperos_keyboard_commit(k,0)) return;
    if(direction<0 && k->cursor) { k->cursor--; while(k->cursor && ((unsigned char)k->request.text[k->cursor]&0xc0)==0x80) k->cursor--; }
    else if(direction>0 && k->request.text[k->cursor]) { k->cursor++; while(((unsigned char)k->request.text[k->cursor]&0xc0)==0x80) k->cursor++; }
}
void paperos_keyboard_mode(PaperOSKeyboard *k,int mode,const char *helper) {
    if(mode==PAPEROS_KB_CHINESE && (k->request.flags&PAPEROS_INPUT_PASSWORD)) return;
    if(!paperos_keyboard_commit(k,0)) return;
    if(mode==PAPEROS_KB_CHINESE && k->engine.child<=0 && !paperos_ime_open(&k->engine,helper)) { message(k,"中文引擎暂不可用，可用英文输入"); return; }
    if(mode==PAPEROS_KB_SYMBOLS) k->symbols_page=k->mode==mode?!k->symbols_page:0;
    k->mode=mode; if(mode<=PAPEROS_KB_UPPER) k->alpha_mode=mode;
    k->message[0]=0;
}
const char *paperos_keyboard_keys(const PaperOSKeyboard *k) {
    switch(k->mode) {
        case PAPEROS_KB_UPPER: return "QWERTYUIOPASDFGHJKLZXCVBNM";
        case PAPEROS_KB_NUMBERS: return "1234567890-/:;()$&@\".,?!'";
        case PAPEROS_KB_SYMBOLS: return "[]{}#%^*+=_\\|~<>`\".,?!'@&$";
        default: return "qwertyuiopasdfghjklzxcvbnm";
    }
}
bool paperos_keyboard_key(const PaperOSKeyboard *k,int index,int *x,int *y,int *w,int *h) {
    const char *keys=paperos_keyboard_keys(k); if(index<0 || index>=26 || index>=(int)strlen(keys)) return false;
    int row,col,offset=19;
    bool letters=k->mode<=PAPEROS_KB_UPPER;
    if(letters) { row=index<10?0:(index<19?1:2); col=index-(row==0?0:(row==1?10:19)); }
    else { row=index/10; col=index%10; }
    if(row==2) offset=103;
    *x=offset+(col*562+5)/10; *y=PAPEROS_KB_GRID_TOP+(row==0?7:(row==1?63:118));
    *w=53; *h=51; return true;
}
bool paperos_keyboard_control(int control,int *x,int *y,int *w,int *h) {
    static const int rects[PAPEROS_KEY_COUNT][4]={
        {16,8,80,48},{480,8,104,48},{104,8,48,48},{424,8,48,48},
        {19,681,81,51},{496,681,82,51},{19,736,81,51},{103,736,53,51},
        {159,736,53,51},{215,736,166,51},{384,736,53,51},{440,736,53,51},
        {496,736,82,51},{522,525,59,38}
    };
    if(control<0 || control>=PAPEROS_KEY_COUNT) return false;
    *x=rects[control][0]; *y=rects[control][1]; *w=rects[control][2]; *h=rects[control][3]; return true;
}
const char *paperos_keyboard_label(const PaperOSKeyboard *k,int control) {
    switch(control) {
        case PAPEROS_KEY_CANCEL: return "取消";
        case PAPEROS_KEY_DONE: return "完成";
        case PAPEROS_KEY_LEFT: return "←";
        case PAPEROS_KEY_RIGHT: return "→";
        case PAPEROS_KEY_SHIFT: return k->mode==PAPEROS_KB_NUMBERS?"#+=":(k->mode==PAPEROS_KB_SYMBOLS?"123":"⇧");
        case PAPEROS_KEY_BACKSPACE: return "⌫";
        case PAPEROS_KEY_LAYOUT: return k->mode<=PAPEROS_KB_UPPER?"123":"ABC";
        case PAPEROS_KEY_LANGUAGE: return k->alpha_mode==PAPEROS_KB_CHINESE?"中":"EN";
        case PAPEROS_KEY_DOT: return ".";
        case PAPEROS_KEY_SPACE: return "空格";
        case PAPEROS_KEY_COMMA: return k->alpha_mode==PAPEROS_KB_CHINESE?"，":",";
        case PAPEROS_KEY_PERIOD: return k->alpha_mode==PAPEROS_KB_CHINESE?"。":"?";
        case PAPEROS_KEY_ENTER: return k->request.flags&PAPEROS_INPUT_MULTILINE?"↵":"完成";
        case PAPEROS_KEY_MORE: return "›";
        default: return "";
    }
}
static bool hit(int x,int y,int left,int top,int width,int height) { return x>=left && x<left+width && y>=top && y<top+height; }
void paperos_keyboard_tap(PaperOSKeyboard *k,int x,int y,const char *helper) {
    if(k->status>=0) return;
    if(y>=PAPEROS_KB_TOP && y<PAPEROS_KB_GRID_TOP+7 && x>=19 && x<509) {
        int index=k->candidate_page*5+(x-19)/98;
        if(index<k->candidate_count) paperos_keyboard_commit(k,index);
        return;
    }
    for(int control=0;control<PAPEROS_KEY_COUNT;control++) {
        int left,top,width,height; paperos_keyboard_control(control,&left,&top,&width,&height);
        if(!hit(x,y,left,top,width,height)) continue;
        switch(control) {
            case PAPEROS_KEY_CANCEL: k->status=PAPEROS_INPUT_CANCELLED; break;
            case PAPEROS_KEY_DONE: if(paperos_keyboard_commit(k,0)) k->status=PAPEROS_INPUT_ACCEPTED; break;
            case PAPEROS_KEY_LEFT: paperos_keyboard_move(k,-1); break;
            case PAPEROS_KEY_RIGHT: paperos_keyboard_move(k,1); break;
            case PAPEROS_KEY_SHIFT:
                if(k->mode==PAPEROS_KB_NUMBERS || k->mode==PAPEROS_KB_SYMBOLS) paperos_keyboard_mode(k,k->mode==PAPEROS_KB_NUMBERS?PAPEROS_KB_SYMBOLS:PAPEROS_KB_NUMBERS,helper);
                else paperos_keyboard_mode(k,k->mode==PAPEROS_KB_UPPER?PAPEROS_KB_LOWER:PAPEROS_KB_UPPER,helper);
                break;
            case PAPEROS_KEY_BACKSPACE: paperos_keyboard_backspace(k); break;
            case PAPEROS_KEY_LAYOUT: paperos_keyboard_mode(k,k->mode<=PAPEROS_KB_UPPER?PAPEROS_KB_NUMBERS:k->alpha_mode,helper); break;
            case PAPEROS_KEY_LANGUAGE: paperos_keyboard_mode(k,k->alpha_mode==PAPEROS_KB_CHINESE?PAPEROS_KB_LOWER:PAPEROS_KB_CHINESE,helper); break;
            case PAPEROS_KEY_DOT: case PAPEROS_KEY_COMMA: case PAPEROS_KEY_PERIOD:
                if(paperos_keyboard_commit(k,0)) paperos_keyboard_insert(k,paperos_keyboard_label(k,control));
                break;
            case PAPEROS_KEY_SPACE:
                if(k->preedit[0]) paperos_keyboard_commit(k,0); else paperos_keyboard_insert(k," "); break;
            case PAPEROS_KEY_ENTER:
                if(paperos_keyboard_commit(k,0)) { if(k->request.flags&PAPEROS_INPUT_MULTILINE) paperos_keyboard_insert(k,"\n"); else k->status=PAPEROS_INPUT_ACCEPTED; } break;
            case PAPEROS_KEY_MORE: if(k->candidate_count>5) k->candidate_page=(k->candidate_page+1)%((k->candidate_count+4)/5); break;
        }
        return;
    }
    if(y>=PAPEROS_KB_GRID_TOP && y<736) {
        /* The native second row has a punctuation key after L. */
        if(k->mode<=PAPEROS_KB_UPPER && hit(x,y,525,626,53,51)) {
            if(paperos_keyboard_commit(k,0)) paperos_keyboard_insert(k,k->mode==PAPEROS_KB_CHINESE?"：":":");
            return;
        }
        const char *keys=paperos_keyboard_keys(k);
        for(int i=0;i<26;i++) {
            int left,top,width,height; if(!paperos_keyboard_key(k,i,&left,&top,&width,&height)) break;
            if(hit(x,y,left,top,width,height)) {
                if(k->mode==PAPEROS_KB_CHINESE) {
                    size_t n=strlen(k->preedit); if(n<32) { k->preedit[n]=keys[i]; k->preedit[n+1]=0; query(k); }
                } else if(paperos_keyboard_commit(k,-1)) { char value[2]={keys[i],0}; paperos_keyboard_insert(k,value); }
                break;
            }
        }
    }
}

#ifndef PAPEROS_NDS_PLAYER_H
#define PAPEROS_NDS_PLAYER_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define PAPEROS_NDS_CORE_REV "422b688009ccb9f2917c086a8fe79c8cecb030ae"
typedef struct {
    bool requested,loaded,initialized,menu,changed,frame_valid,paused,contact,skip_exit_save,confirm_exit;
    char rom[1024],base_data[1024],data[1200],message[256];
    unsigned char digest[32],frame[256*384];
    unsigned buttons,pulse_buttons,pulse_frames,touch_frames;
    int pointer_x,pointer_y,contact_key;
    bool touching;
    uint64_t frames,saved_frame;
    double deadline,measure_at,measured_fps;
    uint64_t measure_frame;
    unsigned video_frames;
} PaperOSNDS;
double paperos_nds_now(void);
bool paperos_nds_open(PaperOSNDS *s);
void paperos_nds_close(PaperOSNDS *s);
bool paperos_nds_save(PaperOSNDS *s,bool resume);
bool paperos_nds_load(PaperOSNDS *s,bool resume);
bool paperos_nds_advance(PaperOSNDS *s,bool blocked);
void paperos_nds_release(PaperOSNDS *s);
bool paperos_nds_contact(PaperOSNDS *s,int x,int y,bool down);
bool paperos_nds_point(int x,int y,int *pointer_x,int *pointer_y);
void paperos_nds_pulse(PaperOSNDS *s,unsigned id);
void paperos_nds_blit(const PaperOSNDS *s,unsigned char *pixels);
#endif

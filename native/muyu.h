#ifndef PAPEROS_MUYU_H
#define PAPEROS_MUYU_H
typedef struct {
    unsigned long long total,today,session;
    char day[11],path[768],message[160];
    bool valid;
    double feedback_until;
} PaperOSMuyu;
#endif

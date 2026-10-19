#ifndef PAPEROS_INPUT_H
#define PAPEROS_INPUT_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PAPEROS_INPUT_MAX 8191
#define PAPEROS_INPUT_TITLE_MAX 128
#define PAPEROS_INPUT_SOCKET "/run/paperos/input.sock"
#define PAPEROS_INPUT_MULTILINE 1U
#define PAPEROS_INPUT_PASSWORD 2U
#define PAPEROS_INPUT_ENGLISH 4U
enum { PAPEROS_INPUT_ACCEPTED=0, PAPEROS_INPUT_CANCELLED=1,
       PAPEROS_INPUT_BUSY=2, PAPEROS_INPUT_FAILED=3, PAPEROS_INPUT_UNAVAILABLE=4 };
typedef struct {
    uint32_t flags, max_bytes;
    char title[PAPEROS_INPUT_TITLE_MAX+1];
    char text[PAPEROS_INPUT_MAX+1];
} PaperOSInputRequest;
typedef struct { uint32_t status; char text[PAPEROS_INPUT_MAX+1]; } PaperOSInputReply;

/* Blocking focus handover. Suspend painting/release touch before calling;
 * repaint/reacquire afterward. The result is unchanged on cancel or failure. */
int paperos_input_text(const char *title,const char *initial,unsigned flags,
                       char *result,size_t capacity);
bool paperos_input_valid_request(const PaperOSInputRequest *request);
bool paperos_input_utf8(const char *text,bool multiline);
bool paperos_input_read_request(int fd,PaperOSInputRequest *request,int timeout_ms);
bool paperos_input_write_request(int fd,const PaperOSInputRequest *request,int timeout_ms);
bool paperos_input_read_reply(int fd,PaperOSInputReply *reply,int timeout_ms);
bool paperos_input_write_reply(int fd,const PaperOSInputReply *reply,int timeout_ms);
#endif

#ifndef PAPEROS_NDS_SHA256_H
#define PAPEROS_NDS_SHA256_H
#include <stddef.h>
#include <stdint.h>
typedef struct { uint32_t h[8]; uint64_t bytes; unsigned used; unsigned char block[64]; } NDSHash;
void nds_hash_init(NDSHash *s);
void nds_hash_update(NDSHash *s,const void *data,size_t size);
void nds_hash_finish(NDSHash *s,unsigned char result[32]);
void nds_hash(const void *data,size_t size,unsigned char result[32]);
#endif

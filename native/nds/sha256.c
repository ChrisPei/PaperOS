/* SHA-256 (FIPS 180-4). Original implementation, GPL-3.0-or-later. */
#include "sha256.h"
#include <string.h>
static uint32_t rotate(uint32_t x,unsigned n){return (x>>n)|(x<<(32-n));}
static void transform(NDSHash *s,const unsigned char *b){
    static const uint32_t k[64]={
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    uint32_t w[64];
    for(unsigned i=0;i<16;i++)w[i]=((uint32_t)b[4*i]<<24)|((uint32_t)b[4*i+1]<<16)|((uint32_t)b[4*i+2]<<8)|b[4*i+3];
    for(unsigned i=16;i<64;i++){
        uint32_t a=w[i-15],z=w[i-2];
        w[i]=w[i-16]+(rotate(a,7)^rotate(a,18)^(a>>3))+w[i-7]+(rotate(z,17)^rotate(z,19)^(z>>10));
    }
    uint32_t a=s->h[0],c=s->h[2],d=s->h[3],e=s->h[4],f=s->h[5],g=s->h[6],h=s->h[7],v=s->h[1];
    for(unsigned i=0;i<64;i++){
        uint32_t t=h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+k[i]+w[i];
        uint32_t u=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&v)^(a&c)^(v&c));
        h=g;g=f;f=e;e=d+t;d=c;c=v;v=a;a=t+u;
    }
    s->h[0]+=a;s->h[1]+=v;s->h[2]+=c;s->h[3]+=d;s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;
}
void nds_hash_init(NDSHash *s){
    *s=(NDSHash){.h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};
}
void nds_hash_update(NDSHash *s,const void *data,size_t size){
    const unsigned char *p=data;s->bytes+=size;
    while(size){size_t n=64-s->used;if(n>size)n=size;memcpy(s->block+s->used,p,n);s->used+=(unsigned)n;p+=n;size-=n;if(s->used==64){transform(s,s->block);s->used=0;}}
}
void nds_hash_finish(NDSHash *s,unsigned char result[32]){
    uint64_t bits=s->bytes*8;unsigned char end=0x80,zero=0;nds_hash_update(s,&end,1);
    while(s->used!=56)nds_hash_update(s,&zero,1);
    unsigned char length[8];for(unsigned i=0;i<8;i++)length[7-i]=(unsigned char)(bits>>(8*i));nds_hash_update(s,length,8);
    for(unsigned i=0;i<32;i++)result[i]=(unsigned char)(s->h[i/4]>>(24-8*(i%4)));
    memset(s,0,sizeof(*s));
}
void nds_hash(const void *data,size_t size,unsigned char result[32]){NDSHash s;nds_hash_init(&s);nds_hash_update(&s,data,size);nds_hash_finish(&s,result);}

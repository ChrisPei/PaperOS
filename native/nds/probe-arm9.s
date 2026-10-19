/* Original tiny DS hardware probe; not a game or a performance proxy for one. */
.syntax unified
.arch armv5te
.arm
.global _start
_start:
    ldr r0, =0x04000304
    ldr r1, =0x8203
    strh r1, [r0]
    ldr r0, =0x04000240
    mov r1, #0x81
    strb r1, [r0]
    mov r1, #0x84
    strb r1, [r0, #2]
    ldr r0, =0x04000000
    ldr r1, =0x10805
    str r1, [r0]
    ldr r2, =0x1000
    str r1, [r0, r2]
    ldr r1, =0x4084
    strh r1, [r0, #0x0e]
    add r3, r0, r2
    strh r1, [r3, #0x0e]
    mov r1, #0x100
    strh r1, [r0, #0x30]
    strh r1, [r0, #0x36]
    strh r1, [r3, #0x30]
    strh r1, [r3, #0x36]
    ldr r0, =0x06000000
    ldr r1, =0x06200000
    mov r2, #0
    ldr r5, =49152
fill:
    tst r2, #128
    ldreq r3, =0x801f
    ldrne r3, =0xffff
    strh r3, [r0], #2
    tst r2, #2048
    ldreq r3, =0x83e0
    ldrne r3, =0xffff
    strh r3, [r1], #2
    add r2, r2, #1
    cmp r2, r5
    blo fill
    ldr r4, =0x02001000
    mov r5, #0
.ifdef IDLE_TEST
    /* VBlank interrupt wakes WFI with IRQ delivery masked. */
    ldr r0, =0x04000004
    mov r1, #8
    strh r1, [r0]
    ldr r0, =0x04000210
    mov r1, #1
    str r1, [r0]
    ldr r0, =0x04000214
idle_frame:
    mov r1, #1
    str r1, [r0]
    mcr p15, 0, r1, c7, c0, 4
    add r5, r5, #1
    str r5, [r4]
    ldr r2, =0x04000130
    ldrh r1, [r2]
    str r1, [r4, #4]
    b idle_frame
.else
    ldr r0, =0x04000006
frame_end:
    ldrh r1, [r0]
    cmp r1, #192
    blo frame_end
    add r5, r5, #1
    str r5, [r4]
    ldr r2, =0x04000130
    ldrh r1, [r2]
    str r1, [r4, #4]
frame_start:
    ldrh r1, [r0]
    cmp r1, #192
    bhs frame_start
    b frame_end
.endif

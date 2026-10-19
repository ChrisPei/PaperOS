.syntax unified
.arch armv4t
.arm
.global _start
_start:
    ldr r0, =0x04000301
    mov r1, #0x80
halt:
    strb r1, [r0]
    b halt

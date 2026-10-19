#!/usr/bin/env python3
"""WSL: build a source-authored DS smoke ROM and pinned static libretro probe.

The ROM exercises two 2D screens, vblank, A input and in-memory state restore.
It contains no Nintendo BIOS/logo or commercial game assets.
"""
from pathlib import Path
import argparse
import os
import struct
import subprocess

REVISION = '422b688009ccb9f2917c086a8fe79c8cecb030ae'
ROOT = Path(__file__).resolve().parents[1]
WORK = Path('/home/chris/kindle-build')
SOURCE = WORK / 'sources/desmume2015'
OUT = ROOT / 'build/nds'

def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)

def crc16(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc

def build_rom(idle=False):
    extra = ['--defsym=IDLE_TEST=1'] if idle else []
    run('arm-linux-gnueabi-as', *extra, '-o', OUT / 'arm9.o', ROOT / 'native/nds/probe-arm9.s')
    run('arm-linux-gnueabi-ld', '-Ttext=0x02000000', '-e', '_start', '-o', OUT / 'arm9.elf', OUT / 'arm9.o')
    run('arm-linux-gnueabi-objcopy', '-O', 'binary', OUT / 'arm9.elf', OUT / 'arm9.bin')
    arm9 = (OUT / 'arm9.bin').read_bytes()
    if idle:
        run('arm-linux-gnueabi-as', '-o', OUT / 'arm7.o', ROOT / 'native/nds/probe-arm7.s')
        run('arm-linux-gnueabi-ld', '-Ttext=0x03800000', '-e', '_start', '-o', OUT / 'arm7.elf', OUT / 'arm7.o')
        run('arm-linux-gnueabi-objcopy', '-O', 'binary', OUT / 'arm7.elf', OUT / 'arm7.bin')
        arm7 = (OUT / 'arm7.bin').read_bytes()
    else:
        arm7 = struct.pack('<I', 0xeafffffe)  # b . (intentionally CPU-bound)
    rom = bytearray(0x10000)
    rom[:12] = b'PAPEROSPROBE'
    rom[12:16] = b'####'  # DeSmuME homebrew classification
    struct.pack_into('<4I', rom, 0x20, 0x200, 0x02000000, 0x02000000, len(arm9))
    struct.pack_into('<4I', rom, 0x30, 0x1000, 0x03800000, 0x03800000, len(arm7))
    struct.pack_into('<II', rom, 0x80, len(rom), 0x200)
    rom[0x200:0x200+len(arm9)] = arm9
    rom[0x1000:0x1000+len(arm7)] = arm7
    struct.pack_into('<H', rom, 0x15c, crc16(rom[0xc0:0x15c]))
    struct.pack_into('<H', rom, 0x15e, crc16(rom[:0x15e]))
    (OUT / ('paperos-idle.nds' if idle else 'paperos-probe.nds')).write_bytes(rom)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rebuild-core', action='store_true')
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        SOURCE.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', '--no-checkout', 'https://github.com/libretro/desmume2015.git', SOURCE)
        run('git', '-C', SOURCE, 'checkout', '--detach', REVISION)
    actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise SystemExit(f'Unexpected DeSmuME revision: {actual}')
    core = WORK / 'desmume2015-arm.a'
    if args.rebuild_core or not core.exists():
        env = dict(os.environ, CFLAGS='-O2 -mcpu=cortex-a9 -marm -mfloat-abi=softfp',
                   CXXFLAGS='-std=gnu++11 -Wno-narrowing')
        run('make', '-f', 'Makefile.libretro', '-j8', 'platform=armv7-cortexa9-softfloat',
            'CC=arm-linux-gnueabi-gcc', 'CXX=arm-linux-gnueabi-g++', 'AR=arm-linux-gnueabi-ar',
            'DESMUME_JIT=0', 'STATIC_LINKING=1', f'TARGET={core}', cwd=SOURCE / 'desmume', env=env)
    build_rom()
    build_rom(idle=True)
    include = SOURCE / 'desmume/src/libretro-common/include'
    run('arm-linux-gnueabi-gcc', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-mcpu=cortex-a9', '-marm', '-mfloat-abi=softfp', f'-I{include}', '-c',
        ROOT / 'native/nds/bench.c', '-o', OUT / 'bench.o')
    run('arm-linux-gnueabi-g++', '-static', '-mcpu=cortex-a9', '-marm', '-mfloat-abi=softfp',
        OUT / 'bench.o', core, '-lpthread', '-lm', '-o', OUT / 'nds-bench')
    run('arm-linux-gnueabi-strip', OUT / 'nds-bench')
    print(OUT / 'nds-bench')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Build and run NDS adapter checks in WSL. Device execution is a separate gate."""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
probe=SourceFileLoader('nds_test_build',str(ROOT/'scripts/build-nds-probe.py')).load_module()
OUT=ROOT/'build/nds/player'

def run(*args,**kwargs):
    result=subprocess.run([str(a) for a in args],**kwargs)
    if result.returncode:
        if result.stdout:print(result.stdout)
        if result.stderr:print(result.stderr)
        result.check_returncode()
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-qemu',action='store_true',help='Optional: this local QEMU has raised SIGILL in the ARM JIT; physical-device checks are separate')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    run('cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',ROOT/'native/nds/sha256.c','-o',OUT/'hash.so')
    library=ctypes.CDLL(str(OUT/'hash.so'))
    library.nds_hash.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p]
    cases=[b'',b'abc',b'a'*1000000,*[os.urandom(n) for n in (55,56,63,64,65,4097)]]
    for data in cases:
        digest=ctypes.create_string_buffer(32);library.nds_hash(data,len(data),digest)
        assert digest.raw==hashlib.sha256(data).digest()
    include=probe.SOURCE/'desmume/src/libretro-common/include'
    flags=['-O2','-mcpu=cortex-a9','-marm','-mfloat-abi=softfp',f'-I{ROOT}/native/nds',f'-I{include}']
    run('arm-linux-gnueabi-gcc','-std=c11','-Wall','-Wextra','-Werror',*flags,'-c',ROOT/'tests/nds-player-device.c','-o',OUT/'device-test.o')
    run('arm-linux-gnueabi-g++','-std=gnu++11',*flags,f'-I{probe.SOURCE}/desmume/src','-c',ROOT/'tests/nds-core-input.cpp','-o',OUT/'input-test.o')
    run('arm-linux-gnueabi-g++','-static',*flags,OUT/'device-test.o',OUT/'input-test.o',
        OUT/'nds-player.c.o',OUT/'nds-sha256.c.o',probe.WORK/'desmume2015-arm.a','-lpthread','-lm','-o',OUT/'nds-player-test')
    run('arm-linux-gnueabi-gcc','-std=c11','-Wall','-Wextra','-Werror',*flags,'-c',ROOT/'tests/nds-game-session.c','-o',OUT/'game-session.o')
    run('arm-linux-gnueabi-g++','-static',*flags,OUT/'game-session.o',OUT/'nds-player.c.o',OUT/'nds-sha256.c.o',
        probe.WORK/'desmume2015-arm.a','-lpthread','-lm','-o',OUT/'nds-game-session')
    record={'sha256_cases':len(cases),'core_selftest_built':True,'qemu_core_test_run':False,
            'actual_game_verified':False}
    if not args.with_qemu:
        (OUT/'validation-host.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps(record,indent=2));return
    with tempfile.TemporaryDirectory(prefix='paperos-nds-test-') as directory:
        args=['qemu-arm-static','-cpu','cortex-a9',OUT/'nds-player-test',ROOT/'build/nds/paperos-idle.nds',directory]
        result=run(*args,capture_output=True,text=True,timeout=60)
        record=next(json.loads(line.split(' ',1)[1]) for line in result.stdout.splitlines() if line.startswith('PAPEROS_NDS_PLAYER_TEST '))
        second=run(*args,str(record['counter']),capture_output=True,text=True,timeout=60)
        assert 'PAPEROS_NDS_REOPEN' in second.stdout
    record['execution_environment']='qemu-arm-static, not physical Kindle'
    record['sha256_cases']=len(cases);record['fresh_process_resume']=True
    (OUT/'validation-host.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()

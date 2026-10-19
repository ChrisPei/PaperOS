#!/usr/bin/env python3
"""Build the separate PaperOS DS app; no ROM or BIOS is bundled."""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
probe=SourceFileLoader('nds_build_probe',str(ROOT/'scripts/build-nds-probe.py')).load_module()
OUT=ROOT/'build/nds/player'

def run(*args):
    subprocess.run([str(a) for a in args],check=True)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    run('python3',ROOT/'scripts/build-nds-probe.py')
    fbink=ROOT/'build/arm/fbink/libfbink.a'
    if not fbink.exists():
        raise SystemExit('Build the existing native FBInk dependency first: scripts/build-native.sh')
    include=probe.SOURCE/'desmume/src/libretro-common/include'
    units=['paperos.c','apps.c','ime.c','input.c','keyboard.c','services.c','calendar.c','nds/player.c','nds/sha256.c']
    objects=[]
    for unit in units:
        output=OUT/(unit.replace('/','-')+'.o')
        run('arm-linux-gnueabi-gcc','-O2','-std=c11','-Wall','-Wextra','-Werror',
            '-mcpu=cortex-a9','-marm','-mfloat-abi=softfp','-DPAPEROS_NDS','-DHAVE_FBINK',
            f'-I{ROOT}/assets',f'-I{ROOT}/tools/FBInk',f'-I{include}',
            '-c',ROOT/'native'/unit,'-o',output)
        objects.append(output)
    binary=OUT/'paperos-nds'
    run('arm-linux-gnueabi-g++','-static','-mcpu=cortex-a9','-marm','-mfloat-abi=softfp',
        *objects,probe.WORK/'desmume2015-arm.a',fbink,'-lpthread','-lm','-o',binary)
    run('arm-linux-gnueabi-strip',binary)
    package=ROOT/'dist/ace-attorney-1.papp';package.mkdir(parents=True,exist_ok=True)
    for name in ('manifest.conf','run.sh'):
        shutil.copyfile(ROOT/'examples/ace-attorney-1.papp'/name,package/name)
    shutil.copyfile(binary,package/'paperos-nds')
    (package/'paperos-nds').chmod(0o755);(package/'run.sh').chmod(0o755)
    shutil.copyfile(ROOT/'LICENSE',package/'COPYING')
    (package/'SOURCE.txt').write_text(
        'PaperOS native sources: native/paperos.c, native/nds/, shared native modules.\n'
        f'DeSmuME2015: https://github.com/libretro/desmume2015/tree/{probe.REVISION}\n'
        'ARM JIT files are GPLv3-or-later; preserve all upstream copyright notices.\n'
        'FBInk revision is recorded in sources.lock.json; no game/BIOS files included.\n')
    record={'core_revision':probe.REVISION,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'binary_bytes':binary.stat().st_size,'rom_bundled':False,
            'validation_scope':'Compilation only; device and game runtime results are recorded separately'}
    (OUT/'build.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()

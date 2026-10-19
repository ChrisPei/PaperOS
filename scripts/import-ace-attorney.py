#!/usr/bin/env python3
"""WSL: atomically import your existing DS game over the pinned SSH connection.

No game is downloaded. Saves remain separated by the complete ROM SHA-256.
The application package is built/installed separately.
"""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import argparse
import hashlib
import ipaddress
import json
import shlex
import struct
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY='/mnt/us/paperos/games/ace-attorney-1'

def inspect_rom(path):
    if path.suffix.lower()!='.nds' or not path.is_file():
        raise ValueError('Choose an existing .nds file')
    size=path.stat().st_size
    if not 512<=size<=128*1024*1024:
        raise ValueError('Supported ROM size: 512 bytes to 128 MiB')
    with path.open('rb') as source:
        header=source.read(512)
        for start,length in ((0x20,0x2c),(0x30,0x3c)):
            offset=struct.unpack_from('<I',header,start)[0]
            count=struct.unpack_from('<I',header,length)[0]
            if not count or offset<512 or offset+count>size:
                raise ValueError('Invalid DS ARM9/ARM7 section bounds')
        source.seek(0);digest=hashlib.file_digest(source,'sha256').hexdigest()
    return {'sha256':digest,'bytes':size,'title':header[:12].rstrip(b'\0').decode('ascii','replace'),
            'game_code':header[12:16].decode('ascii','replace')}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom',type=Path)
    parser.add_argument('--host',default='192.0.2.20')
    parser.add_argument('--inspect-only',action='store_true')
    args=parser.parse_args();ipaddress.ip_address(args.host)
    record=inspect_rom(args.rom)
    if args.inspect_only:
        print(json.dumps(record,ensure_ascii=False,indent=2));return
    ssh=SourceFileLoader('ace_import_ssh',str(ROOT/'scripts/device-ssh.py')).load_module()
    command=ssh.connection(22);command[-1]='root@'+args.host;command[-1:-1]=['-o','HostKeyAlias=169.254.28.2']
    def remote(script,stdin=None,source=None):
        result=subprocess.run(command+[script],input=stdin,stdin=source,capture_output=True,timeout=180)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace')[-2000:] or f'Device exit {result.returncode}')
        return result.stdout.decode()
    digest=record['sha256'];suffix=uuid.uuid4().hex
    temporary=DIRECTORY+'/.import-'+suffix;destination=DIRECTORY+'/'+digest+'.nds'
    q=shlex.quote
    # Immutable hash-named images avoid changing the file a running game is reading.
    with args.rom.open('rb') as source:
        result=remote(f'set -eu; umask 077; mkdir -p {q(DIRECTORY)}; cat > {q(temporary)}; sha256sum {q(temporary)}',source=source)
    if result.split()[0]!=digest:
        remote(f'rm -f {q(temporary)}')
        raise RuntimeError('Device SHA-256 differs; current game was not changed')
    # Publication changes only the current selection. Old images and saves are retained.
    selection=DIRECTORY+'/.current-'+suffix
    remote(f'set -eu; mv {q(temporary)} {q(destination)}; '
           f'printf "%s\\n" {q(digest)} > {q(selection)}; sync; '
           f'mv {q(selection)} {q(DIRECTORY+"/current.sha256")}; sync')
    record['device_path']=destination
    record['gameplay_verified']=False
    print(json.dumps(record,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

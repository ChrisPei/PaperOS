"""Prepare a private, temporary public-key SSH payload from our local build."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path('/home/chris/kindle-build/output-kt3/target')
OUTPUT = ROOT / 'build/usb-debug'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for source, name in ((TARGET / 'usr/sbin/dropbear', 'dropbear'),
                         (TARGET / 'lib/libc.so', 'libc.so')):
        shutil.copyfile(source, OUTPUT / name)
    help_result = subprocess.run(['qemu-arm-static', str(OUTPUT / 'libc.so'), '--library-path', str(OUTPUT),
                                  str(OUTPUT / 'dropbear'), '-h'], text=True, capture_output=True)
    if '-D' not in help_result.stderr or '-s' in help_result.stderr:
        raise ValueError('Expected the configured server with password auth compiled out')
    client = OUTPUT / 'client_ed25519'
    if not client.exists():
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'paperos-device-debug', '-f', str(client)], check=True)
    shutil.copyfile(OUTPUT / 'client_ed25519.pub', OUTPUT / 'authorized_keys')
    hostkey = OUTPUT / 'server_host_key'
    if not hostkey.exists():
        subprocess.run(['qemu-arm-static', str(TARGET / 'lib/libc.so'), '--library-path', str(TARGET / 'lib'),
                        str(TARGET / 'usr/bin/dropbearkey'), '-t', 'ed25519', '-f', str(hostkey)], check=True, capture_output=True)
    key_info = subprocess.check_output(['qemu-arm-static', str(TARGET / 'lib/libc.so'), '--library-path', str(TARGET / 'lib'),
                                       str(TARGET / 'usr/bin/dropbearkey'), '-y', '-f', str(hostkey)], text=True)
    public = next(line for line in key_info.splitlines() if line.startswith('ssh-ed25519 '))
    (OUTPUT / 'known_hosts').write_text('[169.254.28.2]:2222 ' + public + '\n')
    record = {'scope': 'private RAM-only debug payload', 'password_authentication': False,
              'files': {name: hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest()
                        for name in ('dropbear', 'libc.so', 'server_host_key', 'authorized_keys')}}
    (OUTPUT / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'prepared': True, 'runtime_files': 4, 'password_authentication': False}))


if __name__ == '__main__':
    main()

"""Use only the workspace's pinned, public-key USB SSH connection from WSL."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path('/home/chris/kindle-build/private-usb-debug')
OPTIONS = ['-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
           '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']


def connection(port=2222):
    if port not in (22, 2222):
        raise ValueError('Expected the stock debug or independent OS SSH port')
    PRIVATE.mkdir(exist_ok=True, mode=0o700)
    key = PRIVATE / 'client_ed25519'
    shutil.copyfile(ROOT / 'build/usb-debug/client_ed25519', key)
    key.chmod(0o600)
    known = PRIVATE / ('known_hosts' if port == 2222 else 'known_hosts-22')
    pins = (ROOT / 'build/usb-debug/known_hosts').read_text()
    if port == 22:
        pins = pins.replace('[169.254.28.2]:2222 ', '169.254.28.2 ')
    known.write_text(pins)
    return ['ssh', *OPTIONS, '-p', str(port), '-o', 'UserKnownHostsFile=' + str(known), '-i', str(key), 'root@169.254.28.2']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--script', type=Path)
    parser.add_argument('--command')
    parser.add_argument('--port', type=int, choices=(22, 2222), default=2222)
    args = parser.parse_args()
    if bool(args.script) == bool(args.command):
        parser.error('Choose exactly one script or command')
    command = connection(args.port)
    if args.script:
        result = subprocess.run(command + ['/bin/sh', '-s'], input=args.script.read_bytes())
    else:
        result = subprocess.run(command + [args.command])
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()

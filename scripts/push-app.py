"""Transfer a validated .papp over approved Wi-Fi/Tailscale or pinned USB SSH."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tarfile
import uuid
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]


def linux_path(path):
    value = str(path.resolve())
    if len(value) < 3 or value[1:3] != ':\\':
        raise ValueError('Expected a local Windows drive path')
    return '/mnt/' + value[0].lower() + '/' + value[3:].replace('\\', '/')


def archive_package(source):
    if source.is_symlink() or not source.is_dir() or not source.name.endswith('.papp'):
        raise ValueError('Choose a regular .papp directory')
    manifest = source / 'manifest.conf'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 8192:
        raise ValueError('The package must contain a regular manifest.conf')
    content = manifest.read_text(encoding='utf-8')
    ids = [line.split('=', 1)[1] for line in content.splitlines() if line.startswith('id=')]
    if len(ids) != 1 or not re.fullmatch(r'[a-z0-9_-][a-z0-9._-]{0,62}', ids[0]) or '..' in ids[0]:
        raise ValueError('The package has an invalid application id')
    paths = list(source.rglob('*'))
    if len(paths) > 256:
        raise ValueError('The package exceeds 256 entries')
    total = 0
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for path in paths:
            relative = path.relative_to(source)
            info = path.lstat()
            if path.is_symlink() or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError('Packages may contain only regular files and directories')
            if any(ord(char) < 32 or char == '\\' for char in relative.as_posix()):
                raise ValueError('Package paths may not contain control characters or backslashes')
            if len(relative.parts) - int(path.is_file()) > 8:
                raise ValueError('The package exceeds eight nested directories')
            if path.is_file():
                total += info.st_size
                if total > 64 * 1024 * 1024:
                    raise ValueError('The package exceeds 64 MiB')
            archive.add(path, arcname='package/' + relative.as_posix(), recursive=False)
    return ids[0], payload.getvalue()


def transfer(source):
    ident, payload = archive_package(source)
    ssh = SourceFileLoader('paperos_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()

    def remote(command, data=None):
        reply = subprocess.run(ssh.connection(22) + [command], input=data, capture_output=True)
        if reply.returncode:
            raise RuntimeError(reply.stderr.decode('utf-8', 'replace') + reply.stdout.decode('utf-8', 'replace'))
        return reply.stdout

    remote('test "$(readlink /proc/1/exe)" = /bin/busybox && test -f /etc/paperos-release && test -d /mnt/us/paperos/packages')
    token = uuid.uuid4().hex[:12]
    ram = '/run/paperos-package-' + token
    incoming = '/mnt/us/paperos/packages/.incoming-' + token
    previous = '/mnt/us/paperos/packages/.previous-' + token
    destination = '/mnt/us/paperos/packages/' + source.name
    if any(ord(char) < 32 or char == '\\' for char in source.name):
        raise ValueError('The package folder name contains unsupported characters')
    quote = shlex.quote
    try:
        remote(f'umask 077; mkdir {ram} && cat > {ram}/package.tar', payload)
        checksum = hashlib.sha256(payload).hexdigest()
        script = f'''set -eu
echo '{checksum}  {ram}/package.tar' | sha256sum -c -
tar xf {ram}/package.tar -C {ram}
/usr/bin/paperos --app-root {ram}/checked --install {ram}/package
test -s {ram}/checked/{ident}/manifest.conf
test ! -e {incoming}
cp -r {ram}/checked/{ident} {incoming}
sync
if [ -e {quote(destination)} ]; then mv {quote(destination)} {previous}; fi
if ! mv {incoming} {quote(destination)}; then
    if [ -d {previous} ]; then mv {previous} {quote(destination)}; fi
    exit 1
fi
sync
if [ -d {previous} ]; then rm -r {previous}; fi
'''
        remote('/bin/sh -s', script.encode())
        print(f'已传入 {source.name}。在 Kindle「应用 → 接收的应用包」中选择并安装。', flush=True)
    finally:
        remote(f'test ! -d {ram} || rm -r {ram}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('--host', help='Kindle Wi-Fi or Tailscale IPv4 address; confirm on the device')
    parser.add_argument('--usb', action='store_true', help='use the existing pinned USB key channel')
    args = parser.parse_args()
    host = args.host
    peers = ROOT / 'build/wireless-peers.json'
    if not host and not args.usb and peers.is_file():
        import json
        host = json.loads(peers.read_text()).get('default_host')
    if host and not args.usb:
        wireless = SourceFileLoader('paperos_wireless_transfer', str(ROOT / 'scripts/wireless-app.py')).load_module()
        wireless.transfer(args.package.resolve(), host)
        return
    if os.name == 'nt':
        if args.package.is_symlink():
            raise ValueError('Choose a regular .papp directory')
        source = args.package.resolve()
        archive_package(source)  # Reject unsupported input before connecting.
        keepalive = subprocess.Popen(['wsl', '-d', 'Ubuntu-24.04', '--', 'sleep', '180'],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            subprocess.run(['powershell', '-NoProfile', '-File', str(ROOT / 'scripts/connect-device-usb.ps1'),
                            '-Port', '22'], check=True)
            reply = subprocess.run(['wsl', '-d', 'Ubuntu-24.04', '--', 'python3',
                                    linux_path(Path(__file__)), linux_path(source)])
            raise SystemExit(reply.returncode)
        finally:
            keepalive.terminate()
    transfer(args.package)


if __name__ == '__main__':
    main()

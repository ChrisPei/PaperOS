"""Test the static backup tools on the KT3's Linux 3.10 kernel, virtual disk only."""
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import uuid

ROOT = Path('/mnt/d/kindle')
WORK = Path('/home/chris/kindle-build')
MACHINE = WORK / 'paperos-emulator'
DISK = MACHINE / 'disk.img'
TEST = WORK / ('toolbox-validation-' + uuid.uuid4().hex[:12])
OFFSET = 987136 * 512
SIZE = 64 * 1024 * 1024

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)

def control(action):
    run('python3', str(ROOT / 'scripts/emulator-control.py'), action)

def start():
    run('python3', str(ROOT / 'scripts/prepare-emulator.py'), '--start')
    # Avoid sending input during U-Boot's three-second autoboot countdown.
    time.sleep(4)

if DISK.is_symlink() or not DISK.is_file() or DISK.resolve().parent != MACHINE.resolve():
    raise SystemExit('Unexpected emulator backing file')
TEST.mkdir()
test_script = TEST / 'check.sh'
test_script.write_text('''#!/bin/sh
set -eu
PATH=/dev/shm/paperos-backup-tools
export PATH
PAPEROS_TEST=/dev/shm/paperos-backup-tools/fixture
mkdir -p "$PAPEROS_TEST"
cd "$PAPEROS_TEST"
for PAPEROS_TOOL in sha256sum gzip tar df du dd setsid; do command -v "$PAPEROS_TOOL"; done
[ "$(id -u)" = 0 ]
printf 'PaperOS recovery fixture\\n' > data
sha256sum data > SHA256SUMS
sha256sum -c SHA256SUMS
gzip -1 -c data > data.gz
gzip -t data.gz
gzip -d -c data.gz > restored
[ "$(cat restored)" = 'PaperOS recovery fixture' ]
tar -czf archive.tar.gz data
tar -tzf archive.tar.gz | grep -x data
cp data renamed.tmp
chmod 600 renamed.tmp
mv renamed.tmp renamed
rm renamed
dd if=/dev/zero of=large bs=1 count=0 seek=3221225472
[ "$(stat -c %s large)" = 3221225472 ]
rm large
dd if=/dev/zero of=small bs=1048576 count=4
[ "$(wc -c < small)" = 4194304 ]
rm small
df -Pk /dev/shm
PAPEROS_USAGE=$(du -sk .)
PAPEROS_KB=${PAPEROS_USAGE%%[[:space:]]*}
case "$PAPEROS_KB" in ''|*[!0-9]*) exit 1 ;; esac
setsid /dev/shm/paperos-backup-tools/busybox sh -c 'printf detached > /dev/shm/paperos-backup-tools/fixture/detached'
[ "$(cat detached)" = detached ]
mkdir empty
rmdir empty
sync
printf 'PAPEROS_TOOLBOX_PASS\\n'
''')
preflight = TEST / 'preflight.sh'
source_script = (ROOT / 'device-probe/bin/backup-system.sh').read_text()
fixture_script = source_script
fixture_files = []
for original_path, name, value in (
    ('/sys/class/block/mmcblk0/size', 'emmc-sectors', '7634944\n'),
    ('/sys/class/block/mmcblk0p4/start', 'user-start', '1249280\n'),
    ('/sys/class/block/mmcblk0p4/size', 'user-sectors', '6385664\n'),
    ('/proc/mounts', 'mounts', 'rootfs / rootfs rw 0 0\n/dev/root / ext3 ro,noatime,nodiratime,barrier=1,data=ordered 0 0\n'),
):
    fixture_script = fixture_script.replace(original_path, '/usr/share/nh/' + name)
    source = TEST / name
    source.write_text(value)
    fixture_files.append((source, '/' + name))
preflight.write_text(fixture_script)
original = TEST / 'original-p2.img'
fixture = TEST / 'fixture-p2.img'
sock = None
saved = False
control('stop')
try:
    with DISK.open('r+b') as disk:
        disk.seek(OFFSET)
        original.write_bytes(disk.read(SIZE))
        if original.stat().st_size != SIZE:
            raise ValueError('Virtual partition is truncated')
        saved = True
        with fixture.open('xb') as file:
            file.truncate(SIZE)
        run('mkfs.ext3', '-q', '-F', '-O', '^64bit,^metadata_csum,^orphan_file', str(fixture))
        for source, destination in [(ROOT / 'dist/paperos-backup-tools', '/busybox'), (test_script, '/check.sh'), (preflight, '/preflight.sh')] + fixture_files:
            run('debugfs', '-w', '-R', f'write {source} {destination}', str(fixture))
        disk.seek(OFFSET)
        disk.write(fixture.read_bytes())
        disk.flush()
    start()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(MACHINE / 'serial.sock'))
    sock.settimeout(0.5)
    def send(data):
        for offset in range(0, len(data), 8):
            sock.sendall(data[offset:offset + 8])
            time.sleep(0.01)
    def receive(marker, timeout=60):
        data = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                block = sock.recv(65536)
            except socket.timeout:
                continue
            if not block:
                raise RuntimeError('Emulator console disconnected')
            data.extend(block)
            if marker in data:
                return data.decode('utf-8', 'replace')
        raise TimeoutError(repr(data[-700:]))
    send(b'\n')
    receive(b'login:')
    send(b'root\n')
    receive(b'# ')
    send(b'stty -echo\n')
    receive(b'# ')
    def command(text):
        marker = 'PAPEROS_RC_' + uuid.uuid4().hex[:12]
        send((text + f'; PAPEROS_RC=$?; printf "\\n{marker}:%s:END\\n" "$PAPEROS_RC"\n').encode())
        output = receive(b':END')
        match = re.search(re.escape(marker) + r':(\d+):END', output)
        if not match or int(match[1]):
            raise RuntimeError('Guest command failed: ' + output[-2000:])
        return output
    command('mkdir -p /usr/share/nh /dev/shm/paperos-backup-tools; mount -t ext3 /dev/mmcblk0p2 /usr/share/nh && cp /usr/share/nh/busybox /dev/shm/paperos-backup-tools/busybox && chmod 700 /dev/shm/paperos-backup-tools/busybox && /dev/shm/paperos-backup-tools/busybox --install -s /dev/shm/paperos-backup-tools')
    output = command('/dev/shm/paperos-backup-tools/busybox sh /usr/share/nh/check.sh')
    if 'PAPEROS_TOOLBOX_PASS' not in output:
        raise ValueError('Missing test completion marker')
    preflight_output = command('PATH=/dev/shm/paperos-backup-tools /dev/shm/paperos-backup-tools/busybox sh /usr/share/nh/preflight.sh --preflight-only')
    if 'System backup preflight passed.' not in preflight_output:
        raise ValueError('Preflight fixture did not pass')
    rejection_output = command("printf '1\\n' > /usr/share/nh/emmc-sectors; if PATH=/dev/shm/paperos-backup-tools /dev/shm/paperos-backup-tools/busybox sh /usr/share/nh/preflight.sh --preflight-only; then false; else printf 'PAPEROS_WRONG_GEOMETRY_REJECTED\\n'; fi")
    if 'Preflight failed: emmc_sectors:' not in rejection_output:
        raise ValueError('Preflight did not reject incorrect device geometry')
    kernel_output = command('cat /proc/sys/kernel/osrelease')
    if '3.10.53-lab126' not in kernel_output:
        raise ValueError('Kernel is not the probed KT3 kernel')
    result = {'passed': True, 'kernel': '3.10.53-lab126', 'sha256': hashlib.sha256((ROOT / 'dist/paperos-backup-tools').read_bytes()).hexdigest(), 'backup_system_sha256': hashlib.sha256((ROOT / 'device-probe/bin/backup-system.sh').read_bytes()).hexdigest(), 'checks': ['static ARM shell and applets', 'gzip round trip', 'tar gzip listing', 'SHA-256 manifest verification', '3 GiB sparse file geometry', 'byte counting', 'POSIX df and du output', 'setsid child execution', 'preflight with probed geometry and mounts fixture', 'wrong geometry rejected'], 'artifacts': str(TEST)}
    (TEST / 'console.txt').write_text(output + preflight_output + rejection_output + kernel_output)
    (ROOT / 'build/backup-toolbox-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
finally:
    if sock:
        sock.close()
    control('stop')
    if saved:
        with DISK.open('r+b') as disk:
            disk.seek(OFFSET)
            disk.write(original.read_bytes())
            disk.flush()
    start()

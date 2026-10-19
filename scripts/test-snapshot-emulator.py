"""Validate the frozen snapshots on the matching Linux 3.10 KT3 emulator only."""
import base64
import gzip
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
TEST = WORK / ('snapshot-validation-' + uuid.uuid4().hex[:12])
SLOTS = {2: 987136 * 512, 3: 1118208 * 512}
SIZE = 64 * 1024 * 1024

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)

def control(action):
    run('python3', str(ROOT / 'scripts/emulator-control.py'), action)

def start():
    run('python3', str(ROOT / 'scripts/prepare-emulator.py'), '--start')
    time.sleep(4)

if DISK.is_symlink() or not DISK.is_file() or DISK.resolve().parent != MACHINE.resolve():
    raise SystemExit('Unexpected emulator backing file')
TEST.mkdir()
control('stop')
saved = []
sock = None
try:
    with DISK.open('r+b') as disk:
        for slot, offset in SLOTS.items():
            disk.seek(offset)
            original = TEST / f'p{slot}-original.img'
            original.write_bytes(disk.read(SIZE))
            if original.stat().st_size != SIZE:
                raise ValueError('Virtual partition is truncated')
            saved.append((slot, offset, original))
            fixture = TEST / f'p{slot}-fixture.img'
            with fixture.open('xb') as file:
                file.truncate(SIZE)
            run('mkfs.ext3', '-q', '-F', '-O', '^64bit,^metadata_csum,^orphan_file', str(fixture))
            seed = TEST / f'seed{slot}.txt'
            seed.write_text(f'PaperOS frozen snapshot slot {slot}\n', encoding='utf-8')
            run('debugfs', '-w', '-R', f'write {seed} /seed.txt', str(fixture))
            if slot == 2:
                run('debugfs', '-w', '-R', f'write {ROOT}/dist/paperos-snapshot /snapshot', str(fixture))
                run('debugfs', '-w', '-R', 'set_inode_field /snapshot mode 0100755', str(fixture))
            disk.seek(offset)
            disk.write(fixture.read_bytes())
        disk.flush()
    start()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(MACHINE / 'serial.sock'))
    sock.settimeout(0.5)
    def send_console(data):
        # Pace input for the emulated i.MX UART's small receive FIFO.
        for offset in range(0, len(data), 8):
            sock.sendall(data[offset:offset + 8])
            time.sleep(0.01)
    def receive_until(marker, timeout=40):
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
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('Console response too large')
            if marker in data:
                return data.decode('utf-8', 'replace')
        raise TimeoutError(f'Console did not produce {marker!r}: {data[-400:]!r}')
    send_console(b'\n')
    receive_until(b'login:', timeout=60)
    send_console(b'root\n')
    receive_until(b'# ', timeout=20)
    send_console(b'stty -echo\n')
    receive_until(b'# ', timeout=10)
    def command(text, timeout=40):
        marker = 'PAPEROS_DONE_' + uuid.uuid4().hex[:12]
        begin = 'PAPEROS_BEGIN_' + uuid.uuid4().hex[:12]
        send_console((f'printf "\\n{begin}\\n"; ' + text + f'; PAPEROS_RC=$?; printf "\\n{marker}:%s:END\\n" "$PAPEROS_RC"\n').encode())
        output = receive_until(b':END', timeout)
        match = re.search(re.escape(marker) + r':(\d+):END', output)
        if not match or int(match[1]) != 0:
            raise RuntimeError('Guest command failed: ' + output[-700:])
        return output.split(begin, 1)[1].split(marker)[0]
    command('mkdir -p /usr/share/nh /var/local /dev/shm/paperos-snapshot; mount -t ext3 /dev/mmcblk0p2 /usr/share/nh && mount -t ext3 /dev/mmcblk0p3 /var/local')
    results = []
    for slot in SLOTS:
        output = command(f'/usr/share/nh/snapshot --slot {slot}')
        result = json.loads(re.search(r'\{"slot":.*?\}', output).group(0))
        encoded = command(f'gzip -c /dev/shm/paperos-snapshot/p{slot}.img | base64', timeout=60)
        lines = [line.strip() for line in encoded.splitlines() if re.fullmatch(r'[A-Za-z0-9+/=]+', line.strip())]
        decoded = gzip.decompress(base64.b64decode(''.join(lines), validate=True))
        if len(decoded) != SIZE:
            raise ValueError('Snapshot size mismatch')
        snapshot = TEST / f'p{slot}-snapshot.img'
        snapshot.write_bytes(decoded)
        check = run('e2fsck', '-f', '-n', str(snapshot))
        actual_seed = run('debugfs', '-R', 'cat /seed.txt', str(snapshot)).stdout
        if actual_seed != f'PaperOS frozen snapshot slot {slot}\n':
            raise ValueError('Frozen snapshot lost file data')
        result['filesystem_check_passed'] = True
        result['file_contents_preserved'] = True
        results.append(result)
    (TEST / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps({'passed': True, 'results': results, 'artifacts': str(TEST)}))
finally:
    if sock:
        sock.close()
    control('stop')
    with DISK.open('r+b') as disk:
        for _, offset, original in saved:
            disk.seek(offset)
            disk.write(original.read_bytes())
        disk.flush()
    start()

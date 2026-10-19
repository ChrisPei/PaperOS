"""Exercise timed UI exit and real virtual touch events on the KT3 kernel."""
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
TEST = WORK / ('native-preview-validation-' + uuid.uuid4().hex[:12])
OFFSET = 987136 * 512
SIZE = 64 * 1024 * 1024

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)

def control(action, *args):
    return run('python3', str(ROOT / 'scripts/emulator-control.py'), action, *args)

def start():
    run('python3', str(ROOT / 'scripts/prepare-emulator.py'), '--start')
    time.sleep(4)

if DISK.is_symlink() or not DISK.is_file() or DISK.resolve().parent != MACHINE.resolve():
    raise SystemExit('Unexpected emulator backing file')
TEST.mkdir()
original = TEST / 'original-p2.img'
fixture = TEST / 'fixture-p2.img'
sock = None
saved = False
transcript = bytearray()
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
        for source, destination in ((ROOT / 'dist/paperos-kt3', '/preview'), (ROOT / 'assets/NotoSansCJKsc-Regular.otf', '/font.otf'), (ROOT / 'tests/fixtures/agents.tsv', '/agents.tsv')):
            run('debugfs', '-w', '-R', f'write {source} {destination}', str(fixture))
        for directory in ('/packages', '/packages/clock.papp', '/packages/notes.papp'):
            run('debugfs', '-w', '-R', f'mkdir {directory}', str(fixture))
        for package in ('clock.papp', 'notes.papp'):
            for filename in ('manifest.conf', 'run.sh'):
                run('debugfs', '-w', '-R', f'write {ROOT / "examples" / package / filename} /packages/{package}/{filename}', str(fixture))
        run('debugfs', '-w', '-R', 'set_inode_field /preview mode 0100755', str(fixture))
        disk.seek(OFFSET)
        disk.write(fixture.read_bytes())
        disk.flush()
    start()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(MACHINE / 'serial.sock'))
    sock.settimeout(0.5)
    def send(data):
        for offset in range(0, len(data), 4):
            sock.sendall(data[offset:offset + 4])
            time.sleep(0.03)
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
            transcript.extend(block)
            data.extend(block)
            if marker in data:
                return data.decode('utf-8', 'replace')
        raise TimeoutError(repr(data[-1000:]))
    send(b'\n')
    receive(b'login:')
    send(b'root\n')
    receive(b'# ')
    send(b'stty -echo\n')
    receive(b'# ')
    def command(text):
        begin = 'PAPEROS_BEGIN_' + uuid.uuid4().hex[:12]
        marker = 'PAPEROS_RC_' + uuid.uuid4().hex[:12]
        send((f'printf "\\n{begin}\\n"; ' + text + f'; PAPEROS_RC=$?; printf "\\n{marker}:%s:END\\n" "$PAPEROS_RC"\n').encode())
        output = receive(b':END')
        match = re.search(re.escape(marker) + r':(\d+):END', output)
        if not match or int(match[1]):
            raise RuntimeError('Guest command failed: ' + output[-2000:])
        # An interactive ash may still be printing its background-job notice.
        # Wait for its prompt before transmitting the next UART command.
        if '# ' not in output.split(marker, 1)[1]:
            receive(b'# ', 10)
        return output.split(begin, 1)[1].split(marker)[0]
    command('mkdir -p /usr/share/nh; mount -t ext3 /dev/mmcblk0p2 /usr/share/nh; PAPEROS_OLD=$(pidof paperos); for PAPEROS_PID in $PAPEROS_OLD; do kill -STOP "$PAPEROS_PID"; done')
    command('/usr/share/nh/preview --font /usr/share/nh/font.otf --feed /usr/share/nh/agents.tsv --app-root /tmp/preview-apps --packages /usr/share/nh/packages --run-seconds 55 --report /tmp/preview-report.json > /tmp/preview.log 2>&1 & PAPEROS_PREVIEW=$!; for PAPEROS_ATTEMPT in 1 2 3 4 5; do if grep -q "PaperOS live display" /tmp/preview.log; then break; fi; sleep 1; done; grep -q "PaperOS live display" /tmp/preview.log')
    for x, y in ((230, 746), (80, 746), (500, 746), (80, 746)):
        control('tap', '--x', str(x), '--y', str(y))
        time.sleep(0.25)
    for x, y in ((300, 681), (440, 190), (200, 260), (160, 375), (440, 190), (200, 350), (160, 375), (80, 746), (140, 400)):
        control('tap', '--x', str(x), '--y', str(y))
        time.sleep(0.35)
    command('for PAPEROS_ATTEMPT in 1 2 3 4 5; do if [ "$(grep -c \'PaperOS live display\' /tmp/preview.log)" -ge 2 ]; then break; fi; sleep 1; done; test "$(grep -c \'PaperOS live display\' /tmp/preview.log)" -ge 2')
    control('capture', '--name', 'launcher-child-clock')
    control('tap', '--x', '300', '--y', '746')
    command('for PAPEROS_ATTEMPT in 1 2 3 4 5; do if [ "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 3 ]; then break; fi; sleep 1; done; test "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 3')
    time.sleep(0.25)
    control('capture', '--name', 'launcher-app-return')
    control('tap', '--x', '430', '--y', '400')
    command('for PAPEROS_ATTEMPT in 1 2 3 4 5; do if [ "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 4 ]; then break; fi; sleep 1; done; test "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 4')
    time.sleep(0.3)
    for x, y in ((50, 440), (490, 640), (300, 746)):
        control('tap', '--x', str(x), '--y', str(y))
        time.sleep(0.3)
    command('for PAPEROS_ATTEMPT in 1 2 3 4 5; do if [ "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 5 ]; then break; fi; sleep 1; done; test "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 5')
    for x, y in ((360, 746), (200, 260), (450, 375), (450, 375), (80, 746)):
        control('tap', '--x', str(x), '--y', str(y))
        time.sleep(0.3)
    control('capture', '--name', 'app-panel-after-uninstall')
    command('test ! -d /tmp/preview-apps/org.paperos.clock || { cat /tmp/preview.log; ls /tmp/preview-apps; false; }')
    control('tap', '--x', '140', '--y', '400')
    command('for PAPEROS_ATTEMPT in 1 2 3 4 5; do if [ "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 6 ]; then break; fi; sleep 1; done; test "$(grep -c \'PaperOS interface ready\' /tmp/preview.log)" -ge 6')
    time.sleep(0.3)
    control('capture', '--name', 'notes-independent-persisted')
    control('tap', '--x', '300', '--y', '746')
    command('wait "$PAPEROS_PREVIEW"')
    report_output = command('cat /tmp/preview-report.json')
    report = json.loads(re.search(r'\{[^\r\n]+\}', report_output)[0])
    note = command('cat /tmp/preview-apps/.data/org.paperos.notes/note.txt').strip()
    log = command('cat /tmp/preview.log')
    if report['width'] != 600 or report['height'] != 800 or report['display_errors'] or report['touch_events'] != 20 or report['screens_seen'] != 115 or note != 'q' or report['apps_installed'] != 2 or report['apps_removed'] != 1 or report['apps_launched'] != 3 or report['app_returns'] != 3:
        raise ValueError('Native event/timeout test failed: ' + json.dumps(report))
    result = {'passed': True, 'kernel': '3.10.53-lab126', 'native_sha256': hashlib.sha256((ROOT / 'dist/paperos-kt3').read_bytes()).hexdigest(), 'report': report, 'auto_exit_seconds': 55, 'note_contents_preserved': True, 'application_install_launch_and_return': True, 'uninstall_removes_home_entry': True, 'independent_notes_application': True, 'artifacts': str(TEST)}
    (TEST / 'console.txt').write_text(report_output + log)
    (ROOT / 'build/native-preview-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
finally:
    (TEST / 'transcript.txt').write_bytes(transcript)
    if sock:
        sock.close()
    control('stop')
    if saved:
        with DISK.open('r+b') as disk:
            disk.seek(OFFSET)
            disk.write(original.read_bytes())
            disk.flush()
    start()

"""Deploy a bounded launcher/app trial through the pinned USB SSH connection."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import re
import subprocess
import tarfile
import uuid

from importlib.util import spec_from_file_location, module_from_spec

ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location('device_ssh', ROOT / 'scripts/device-ssh.py')
ssh = module_from_spec(spec)
spec.loader.exec_module(ssh)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    if args.stop and not args.collect:
        parser.error('--stop requires --collect')
    if args.collect:
        state = json.loads((ROOT / 'build/device-launcher-trial.json').read_text())
        directory = state['directory']
        if not re.fullmatch(r'/dev/shm/paperos-launcher-trial-[0-9a-f]{12}', directory):
            raise ValueError('Unexpected trial directory')
        transport = ssh.connection()
        if args.stop:
            stop = f'''for p in /proc/[0-9]*/exe; do
    if [ "$(/bin/busybox readlink "$p")" = {directory}/paperos-preview ]; then
        n=${{p#/proc/}}; n=${{n%/exe}}; kill "$n"
    fi
done
/bin/busybox sleep 4
'''
            subprocess.run(transport + ['/bin/sh', '-s'], input=stop.encode(), check=True)
        status = subprocess.check_output(transport + [f'cat {directory}/status.txt'], text=True).strip()
        if status == 'RUNNING':
            print(json.dumps({'status': status, 'directory': directory}))
            return
        report = json.loads(subprocess.check_output(transport + [f'cat {directory}/report.json'], text=True))
        log = subprocess.check_output(transport + [f'cat {directory}/preview.log'], text=True)
        restored = subprocess.check_output(transport + ['initctl status x; initctl status lab126_gui; initctl status framework; initctl status kppmainapp'], text=True)
        state.update(status=status, report=report, stock_services=restored.splitlines(),
                     passed=status == 'DONE' and not report['display_errors'] and report['touch_present'] and 'stop/waiting' not in restored,
                     application_handover_verified=report['apps_launched'] > 0 and report['app_returns'] == report['apps_launched'])
        logs = ROOT / 'build/device-launcher-reports' / directory.rsplit('-', 1)[1]
        logs.mkdir(parents=True, exist_ok=True)
        note = subprocess.run(transport + [f'cat {directory}/apps/.data/org.paperos.notes/note.txt'],
                              capture_output=True, check=False)
        if note.returncode == 0:
            if len(note.stdout) > 2047:
                raise ValueError('Unexpected trial note size')
            (logs / 'note.txt').write_bytes(note.stdout)
            state.update(notes_saved_bytes=len(note.stdout),
                         notes_sha256=hashlib.sha256(note.stdout).hexdigest(),
                         chinese_note_saved='你好'.encode() in note.stdout)
        (logs / 'preview.log').write_text(log)
        (logs / 'validation.json').write_text(json.dumps(state, indent=2) + '\n')
        (ROOT / 'build/device-launcher-validation.json').write_text(json.dumps(state, indent=2) + '\n')
        print(json.dumps(state))
        return
    backup = json.loads((ROOT / 'build/full-backup-state.json').read_text(encoding='utf-8-sig'))
    validation = json.loads((ROOT / 'build/native-preview-validation.json').read_text())
    program = ROOT / 'dist/paperos-kt3'
    checksum = hashlib.sha256(program.read_bytes()).hexdigest()
    if not backup['complete'] or not validation['passed'] or validation['native_sha256'] != checksum:
        raise ValueError('A complete backup and matching emulator validation are required')
    transport = ssh.connection()
    subprocess.run(transport + ["test \"$(id -u)\" = 0 && test \"$(cat /proc/bootmode)\" = main && test -e /dev/shm/paperos-usb-debug/connected"], check=True)
    directory = '/dev/shm/paperos-launcher-trial-' + uuid.uuid4().hex[:12]
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for path, name in ((program, 'paperos'),
                           (ROOT / 'assets/NotoSansCJKsc-Regular.otf', 'font.otf'),
                           (ROOT / 'build/preview-agents.tsv', 'agents.tsv'),
                           (ROOT / 'device-probe/bin/run-hardware-preview.sh', 'run-hardware-preview.sh'),
                           (ROOT / 'examples/clock.papp', 'packages/clock.papp'),
                           (ROOT / 'examples/notes.papp', 'packages/notes.papp')):
            archive.add(path, arcname=name)
        ime_proof = ROOT / 'build/stock-ime-validation.json'
        if ime_proof.is_file():
            ime = json.loads(ime_proof.read_text())
            runtime = Path(ime['fixture']) / 'root'
            if not ime['passed'] or hashlib.sha256((runtime / 'probe').read_bytes()).hexdigest() != ime['program_sha256']:
                raise ValueError('IME compatibility helper changed after validation')
            for path in runtime.rglob('*'):
                if path.is_file() and path.name != 'emulator':
                    archive.add(path, arcname='ime-runtime/' + str(path.relative_to(runtime)), recursive=False)
    quoted = shlex.quote(directory)
    unpack = (f'umask 077; mkdir {quoted} && mkdir {quoted}/source && '
              f'/bin/busybox tar xf - -C {quoted}/source && '
              f'cp {quoted}/source/run-hardware-preview.sh {quoted}/run-hardware-preview.sh')
    subprocess.run(transport + [unpack], input=payload.getvalue(), check=True)
    remote_hash = subprocess.check_output(transport + [f'/dev/shm/paperos-backup-tools/busybox sha256sum {quoted}/source/paperos'], text=True).split()[0]
    if remote_hash != checksum:
        raise ValueError('Uploaded program checksum mismatch')
    launch = (f'PAPEROS_SOURCE={quoted}/source PAPEROS_RAM={quoted} PAPEROS_DURATION=300 PAPEROS_PREINSTALL=1 '
              'PATH=/dev/shm/paperos-backup-tools:/usr/sbin:/usr/bin:/sbin:/bin '
              f'/dev/shm/paperos-backup-tools/busybox setsid /dev/shm/paperos-backup-tools/busybox sh {quoted}/run-hardware-preview.sh '
              f'< /dev/null > {quoted}/launch.log 2>&1 &')
    subprocess.run(transport + [launch], check=True)
    state = {'directory': directory, 'duration_seconds': 300, 'native_sha256': checksum,
             'results_in_ram': True, 'writes_block_devices': False, 'changes_bootmode': False}
    (ROOT / 'build/device-launcher-trial.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state))


if __name__ == '__main__':
    main()

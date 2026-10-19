"""Prepare a private per-device filesystem. This never opens a block device."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
SIZE = 64 * 1024 * 1024


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--size-mib', type=int, choices=(64,256), default=64)
    args = parser.parse_args()
    size = args.size_mib * 1024 * 1024
    backup = json.loads((ROOT / 'build/full-backup-state.json').read_text(encoding='utf-8-sig'))
    inspection = json.loads((ROOT / 'build/device-backup-inspection/inspection.json').read_text())
    ime = json.loads((ROOT / 'build/stock-ime-validation.json').read_text())
    if not backup['complete'] or not inspection['backup_bytes_verified'] or not ime['passed']:
        raise ValueError('A complete verified backup and input-engine validation are required')
    runtime = Path(ime['fixture']) / 'root'
    if digest(runtime / 'probe') != ime['program_sha256']:
        raise ValueError('IME helper changed after validation')
    directory = ROOT / 'build' / ('device-rootfs-' + uuid.uuid4().hex[:12])
    directory.mkdir()
    image = directory / ('recovery.ext3' if args.size_mib==64 else 'system.ext3')
    base = ROOT / 'dist/paperos-kt3-rootfs.ext3'
    shutil.copyfile(base, image)
    if image.is_symlink() or image.resolve().parent != directory.resolve():
        raise ValueError('Expected an owned, regular filesystem image')
    records = []
    operations = []
    folders = set()

    def add(source, destination, mode):
        parent = Path(destination).parent
        parents = [parent]
        while str(parent) != '/':
            parent = parent.parent
            parents.append(parent)
        for parent in reversed(parents):
            if str(parent) != '/' and str(parent) not in folders:
                operations.append('mkdir ' + str(parent))
                folders.add(str(parent))
        operations.extend((f'rm {destination}', f'write {source} {destination}',
                           f'set_inode_field {destination} mode {mode}',
                           f'set_inode_field {destination} uid 0', f'set_inode_field {destination} gid 0'))
        records.append({'source': str(source), 'destination': destination, 'sha256': digest(source)})

    for source in runtime.rglob('*'):
        if source.is_file() and source.name != 'emulator':
            add(source, '/usr/lib/paperos-ime-root/' + str(source.relative_to(runtime)),
                '0100755' if source.name in ('probe', 'ld-linux.so.3') else '0100644')
    waveform_record = next(row for row in inspection['waveforms']['private_records'] if row['path'].startswith('./waveform_to_use/'))
    waveform = ROOT / 'build/device-backup-inspection/waveforms' / waveform_record['path'].removeprefix('./')
    if digest(waveform) != waveform_record['sha256']:
        raise ValueError('Original display waveform checksum mismatch')
    add(waveform, '/lib/firmware/imx/epdc_EANAB.fw', '0100644')
    private = ROOT / 'build/usb-debug'
    add(private / 'authorized_keys', '/root/.ssh/authorized_keys', '0100600')
    add(private / 'server_host_key', '/root/.ssh/server_host_key', '0100600')
    add(ROOT / 'os/rootfs-overlay/etc/init.d/S50dropbear', '/etc/init.d/S50dropbear', '0100755')
    add(ROOT / 'os/rootfs-overlay/etc/init.d/S40paperos-usb', '/etc/init.d/S40paperos-usb', '0100755')
    # Keep the user's hardware-test note when moving into the independent OS.
    note_proof = ROOT / 'build/device-launcher-validation.json'
    if note_proof.is_file():
        trial = json.loads(note_proof.read_text())
        trial_id = trial.get('directory', '').rsplit('-', 1)[-1]
        if len(trial_id) != 12 or any(c not in '0123456789abcdef' for c in trial_id):
            raise ValueError('Unexpected hardware note evidence directory')
        note = ROOT / 'build/device-launcher-reports' / trial_id / 'note.txt'
        if trial.get('passed') and note.is_file():
            if note.is_symlink() or note.stat().st_size > 2047:
                raise ValueError('Unexpected hardware note file')
            if trial.get('notes_sha256') and digest(note) != trial['notes_sha256']:
                raise ValueError('Hardware note changed after collection')
            add(note, '/var/lib/paperos/apps/.data/org.paperos.notes/note.txt', '0100600')
    wrapper = directory / 'paperos-ime'
    wrapper.write_text('#!/bin/sh\nPAPEROS_IME_ROOT=/usr/lib/paperos-ime-root\nexec "$PAPEROS_IME_ROOT/lib/ld-linux.so.3" --library-path "$PAPEROS_IME_ROOT/lib:$PAPEROS_IME_ROOT/usr/lib" "$PAPEROS_IME_ROOT/probe" --root "$PAPEROS_IME_ROOT" "$@"\n')
    add(wrapper, '/usr/sbin/paperos-ime', '0100755')
    environment = directory / 'paperos.env'
    environment.write_text((ROOT / 'os/rootfs-overlay/etc/paperos.env').read_text() + '\nPAPEROS_IME_HELPER=/usr/sbin/paperos-ime\n')
    add(environment, '/etc/paperos.env', '0100600')
    operations.extend(('set_inode_field /root mode 040700', 'set_inode_field /root/.ssh mode 040700'))
    commands = directory / 'provision.debugfs'
    commands.write_text('\n'.join(operations) + '\n')
    result = run('debugfs', '-w', '-f', str(commands), str(image))
    (directory / 'provision.log').write_text(result.stdout + result.stderr)
    for number, record in enumerate(records):
        check = directory / f'check-{number}'
        run('debugfs', '-R', f'dump {record["destination"]} {check}', str(image))
        if digest(check) != record['sha256']:
            raise ValueError('Provisioned file checksum mismatch: ' + record['destination'])
        check.unlink()
    run('e2fsck', '-f', '-y', str(image))
    run('resize2fs', str(image), str(args.size_mib)+'M')
    with image.open('r+b') as file:
        file.truncate(size)
    run('e2fsck', '-f', '-n', str(image))
    record = {'prepared': True, 'image': str(image), 'bytes': image.stat().st_size, 'sha256': digest(image),
              'base_sha256': digest(base), 'private_provisioning': records,
              'starts_launcher_at_boot': True, 'contains_device_waveform': True,
              'original_chinese_input_engine': True, 'usb_public_key_recovery': True,
              'wifi_driver_provisioned': True, 'wifi_hardware_verified': False,
              'hardware_boot_verified': False, 'writes_block_devices': False}
    state_name = 'device-recovery-rootfs.json' if args.size_mib==64 else 'device-main-rootfs.json'
    (ROOT / 'build' / state_name).write_text(json.dumps(record, indent=2) + '\n')
    if args.size_mib==64:
        (ROOT / 'build/device-rootfs.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: value for key, value in record.items() if key != 'private_provisioning'}))


if __name__ == '__main__':
    main()

"""Inspect the verified local backup without opening any physical device."""
import hashlib
import json
from pathlib import Path, PureWindowsPath
import struct
import subprocess
import tarfile
import zlib

ROOT = Path('/mnt/d/kindle')
state = json.loads((ROOT / 'build/full-backup-state.json').read_text(encoding='utf-8-sig'))
if state['complete'] is not True:
    raise SystemExit('Complete byte-verified private backup is required')
relative = PureWindowsPath(state['directory']).relative_to(PureWindowsPath('D:/kindle/backups'))
backup = ROOT / 'backups' / Path(*relative.parts)
if backup.resolve().parent != (ROOT / 'backups').resolve():
    raise SystemExit('Unexpected private backup directory')
output = ROOT / 'build/device-backup-inspection'
output.mkdir(exist_ok=True)
prefix = backup / 'emmc-prefix.img'
with prefix.open('rb') as file:
    reserved = file.read(32 * 1024 * 1024)
main = output / 'mmcblk0p1.img'
if not main.exists():
    with prefix.open('rb') as source, main.open('xb') as target:
        source.seek(32 * 1024 * 1024)
        remaining = 450 * 1024 * 1024
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError('Truncated system partition')
            target.write(block)
            remaining -= len(block)
if main.stat().st_size != 450 * 1024 * 1024:
    raise ValueError('Invalid system partition size')
result = {'backup_bytes_verified': True, 'filesystems': [], 'kernels': [], 'waveforms': {}}
for slot, image in ((1, main), (2, backup / 'mmcblk0p2.img'), (3, backup / 'mmcblk0p3.img')):
    check = subprocess.run(['e2fsck', '-f', '-n', str(image)], capture_output=True, text=True)
    (output / f'p{slot}-e2fsck.txt').write_text(check.stdout + check.stderr)
    result['filesystems'].append({'slot': slot, 'check_exit': check.returncode, 'passed': check.returncode == 0})
    print(json.dumps({'slot': slot, 'filesystem_check_passed': check.returncode == 0}), flush=True)
offset = 0
while True:
    offset = reserved.find(b'\x27\x05\x19\x56', offset)
    if offset < 0:
        break
    if offset + 64 > len(reserved):
        break
    header = bytearray(reserved[offset:offset + 64])
    fields = struct.unpack('>7I4B32s', header)
    header[4:8] = bytes(4)
    size = fields[3]
    if zlib.crc32(header) == fields[1] and offset + 64 + size <= len(reserved):
        data = reserved[offset + 64:offset + 64 + size]
        valid = zlib.crc32(data) == fields[6]
        entry = {'offset': offset, 'payload_bytes': size, 'header_crc_valid': True, 'payload_crc_valid': valid, 'os': fields[7], 'arch': fields[8], 'type': fields[9], 'compression': fields[10], 'sha256': hashlib.sha256(reserved[offset:offset + 64 + size]).hexdigest()}
        result['kernels'].append(entry)
        if valid:
            (output / f'kernel-{offset:08x}.uimage').write_bytes(reserved[offset:offset + 64 + size])
    offset += 4
for name, start in (('main', 0x41000), ('diags', 0xe41000)):
    if reserved[start:start + 4] == b'\xd0\x0d\xfe\xed':
        total = struct.unpack_from('>I', reserved, start + 4)[0]
        if 40 <= total <= 102400:
            (output / f'{name}.dtb').write_bytes(reserved[start:start + total])
            result[name + '_dtb_bytes'] = total
diag_init = subprocess.run(['debugfs', '-R', 'stat /sbin/init', str(backup / 'mmcblk0p2.img')], capture_output=True, text=True)
result['original_p2_has_init'] = 'Inode:' in diag_init.stdout
with tarfile.open(backup / 'waveform-files.tar.gz', 'r:gz') as archive:
    records = []
    for member in archive.getmembers():
        parts = Path(member.name).parts
        if member.name.startswith('/') or '..' in parts or not (member.isdir() or member.isfile()):
            raise ValueError('Unexpected waveform archive member')
        if member.isfile():
            if member.size > 64 * 1024 * 1024:
                raise ValueError('Waveform file too large')
            data = archive.extractfile(member).read()
            records.append({'path': member.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            target = output / 'waveforms' / Path(member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    result['waveforms'] = {'files': len(records), 'uncompressed_bytes': sum(x['bytes'] for x in records), 'private_records': records}
(output / 'inspection.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'kernels': result['kernels'], 'main_dtb_bytes': result.get('main_dtb_bytes'), 'diags_dtb_bytes': result.get('diags_dtb_bytes'), 'original_p2_has_init': result['original_p2_has_init'], 'waveform_file_count': result['waveforms']['files'], 'all_filesystems_passed': all(x['passed'] for x in result['filesystems'])}), flush=True)

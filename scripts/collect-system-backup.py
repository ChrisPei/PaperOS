"""Verify private device dumps and assemble a complete eMMC user-area image."""
import gzip
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / 'build/full-backup-state.json'
state = json.loads(STATE_PATH.read_text(encoding='utf-8-sig'))
destination = Path(state['directory']).resolve()
if not destination.is_relative_to((ROOT / 'backups').resolve()):
    raise ValueError('Backup directory escapes private workspace backups')
if not state['p4_sha256'] or state['p4_written_bytes'] != state['p4_bytes']:
    raise ValueError('USB user-partition backup must be verified first')
source = Path('G:/paperos/recovery-backup')
owner = 'paperos-recovery-backup-v1'
if (source / 'OWNER').read_text().strip() != owner or (source / 'COMPLETE').read_text().strip() != owner:
    raise ValueError('Device backup did not complete')
allowed = {
    'emmc-prefix.img', 'mmcblk0p2.img.gz', 'mmcblk0p3.img.gz',
    'mmcblk0boot0.img', 'mmcblk0boot1.img', 'waveform-files.tar.gz',
    'snapshot-p2.json', 'snapshot-p3.json', 'hardware-details.txt', 'OWNER',
}
expected = {}
for line in (source / 'SHA256SUMS').read_text().splitlines():
    sha, name = line.split(maxsplit=1)
    name = name.lstrip('*')
    if name not in allowed or name in expected or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('Unexpected device manifest member')
    expected[name] = sha
if set(expected) != allowed:
    raise ValueError('Device manifest is missing regions')

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()

def save_state():
    state['updated_utc'] = datetime.now(timezone.utc).isoformat()
    text = json.dumps(state, ensure_ascii=False, indent=2) + '\n'
    STATE_PATH.write_text(text, encoding='utf-8')
    (destination / 'manifest.json').write_text(text, encoding='utf-8')

for name, sha in expected.items():
    target = destination / name
    if target.exists():
        if digest(target) != sha:
            raise ValueError('Existing saved region has a different hash')
        continue
    partial = destination / (name + '.' + uuid.uuid4().hex[:8] + '.partial')
    with (source / name).open('rb') as incoming, partial.open('xb') as output:
        shutil.copyfileobj(incoming, output, 1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
    if digest(partial) != sha:
        raise ValueError('Copied region did not match its device SHA-256')
    partial.rename(target)
    print('Verified device region: ' + name, flush=True)
for name in ('SHA256SUMS', 'COMPLETE', 'status.txt', 'backup.log', 'launch.log', 'launch-child.log'):
    shutil.copyfile(source / name, destination / name)
if (destination / 'emmc-prefix.img').stat().st_size != state['p4_offset']:
    raise ValueError('eMMC prefix size mismatch')
for slot in (0, 1):
    if (destination / f'mmcblk0boot{slot}.img').stat().st_size != 4194304:
        raise ValueError('Boot partition size mismatch')
for slot in (2, 3):
    target = destination / f'mmcblk0p{slot}.img'
    if not target.exists():
        partial = destination / (target.name + '.' + uuid.uuid4().hex[:8] + '.partial')
        with gzip.open(destination / f'mmcblk0p{slot}.img.gz', 'rb') as incoming, partial.open('xb') as output:
            shutil.copyfileobj(incoming, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if partial.stat().st_size != 67108864:
            raise ValueError('Frozen filesystem snapshot size mismatch')
        partial.rename(target)
    if target.stat().st_size != 67108864:
        raise ValueError('Frozen filesystem snapshot size mismatch')
with (destination / 'emmc-prefix.img').open('rb') as file:
    header = file.read(512)
if header[510:512] != b'\x55\xaa':
    raise ValueError('Device MBR signature is invalid')
for index, (start, length) in enumerate(((65536, 921600), (987136, 131072), (1118208, 131072), (1249280, 6385664))):
    actual = struct.unpack_from('<II', header, 446 + 16 * index + 8)
    if actual != (start, length):
        raise ValueError('MBR geometry does not match the root probe')
state['system_regions_received'] = True
state['boot_partitions_received'] = True
state['status'] = 'assembling_full_emmc_image'
state['region_sha256'] = expected
save_state()
image = destination / 'mmcblk0.img'
if image.exists():
    raise ValueError('Complete image already exists; preserve it before reassembly')
partial_image = destination / ('mmcblk0.img.' + uuid.uuid4().hex[:8] + '.partial')
with partial_image.open('x+b') as output:
    for name in ('emmc-prefix.img', 'mmcblk0p4.img'):
        incoming_hash = hashlib.sha256()
        copied = 0
        with (destination / name).open('rb') as incoming:
            for block in iter(lambda: incoming.read(1024 * 1024), b''):
                output.write(block)
                incoming_hash.update(block)
                copied += len(block)
        expected_size = state['p4_offset'] if name == 'emmc-prefix.img' else state['p4_bytes']
        expected_hash = expected[name] if name == 'emmc-prefix.img' else state['p4_sha256']
        if copied != expected_size or incoming_hash.hexdigest() != expected_hash:
            raise ValueError('Assembly source region does not match its verified capture')
    for slot, offset in ((2, 987136 * 512), (3, 1118208 * 512)):
        output.seek(offset)
        with (destination / f'mmcblk0p{slot}.img').open('rb') as incoming:
            shutil.copyfileobj(incoming, output, 1024 * 1024)
    output.flush()
    os.fsync(output.fileno())
if partial_image.stat().st_size != state['emmc_bytes']:
    raise ValueError('Complete eMMC image size mismatch')
state['emmc_sha256'] = digest(partial_image)
partial_image.rename(image)
state['complete'] = True
state['status'] = 'full_emmc_user_area_and_both_boot_partitions_verified'
state['scope'] = 'eMMC user area + boot0 + boot1; secure RPMB is not changed or imaged'
state['consistency'] = 'USB filesystem locked; root mounted read-only; p2/p3 frozen separately for RAM snapshots; per-filesystem capture times differ'
save_state()
print(json.dumps({'complete': True, 'emmc_bytes': state['emmc_bytes'], 'directory': str(destination)}))

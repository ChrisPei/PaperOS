"""Reversible stock-system development setup over the pinned USB connection.

Save the exact files locally before renaming OTA executables. Install only our
own Upstart job, and always return the root filesystem to read-only mode.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import uuid
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
ssh = SourceFileLoader('paperos_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()
OWNER = '# paperos-usb-devbridge-v1'


def remote(command, data=None):
    return subprocess.run(ssh.connection() + [command], input=data, check=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    backup = json.loads((ROOT / 'build/full-backup-state.json').read_text(encoding='utf-8-sig'))
    if not backup['complete']:
        raise ValueError('Verified full-device backup is required')
    remote('test "$(id -u)" = 0 && test "$(cat /proc/bootmode)" = main && test -e /dev/shm/paperos-usb-debug/connected')
    record_path = ROOT / 'build/device-development-setup.json'
    if args.restore:
        state = json.loads(record_path.read_text())
        actions = []
        for item in state['ota_files']:
            path = item['path']
            if path not in ('/usr/bin/otaupd', '/usr/bin/otav3'):
                raise ValueError('Unexpected restore target')
            actions.extend((f'test ! -e {path}',
                            f'echo "{item["sha256"]}  {path}.paperos-disabled" | /dev/shm/paperos-backup-tools/busybox sha256sum -c -',
                            f'mv {path}.paperos-disabled {path}'))
        script = f'''set -eu
test "$(head -n 1 /etc/upstart/paperos-devbridge.conf)" = '{OWNER}'
mntroot rw
trap 'sync; mntroot ro' EXIT
{chr(10).join(actions)}
rm /etc/upstart/paperos-devbridge.conf
rm -f /mnt/us/paperos/usb-debug/AUTOSTART
rm -f /var/local/paperos-usb-debug/AUTOSTART
initctl reload-configuration
'''
        remote('/bin/sh -s', script.encode())
        state.update(installed=False, ota_blocked=False)
    else:
        directory = ROOT / 'build' / ('device-development-backup-' + uuid.uuid4().hex[:12])
        directory.mkdir()
        records = []
        for name in ('otaupd', 'otav3'):
            path = '/usr/bin/' + name
            data = remote('cat ' + path)
            if not data.startswith(b'\x7fELF\x01'):
                raise ValueError('Expected the original ARM OTA executable')
            (directory / name).write_bytes(data)
            records.append({'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        job = (ROOT / 'device-probe/paperos-devbridge.conf').read_bytes()
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w') as archive:
            info = tarfile.TarInfo('paperos-devbridge.conf')
            info.size = len(job)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(job))
        ram = '/dev/shm/paperos-development-' + uuid.uuid4().hex[:12]
        remote(f'umask 077; mkdir {ram} && /bin/busybox tar xf - -C {ram}', payload.getvalue())
        actions = []
        for item in records:
            path = item['path']
            actions.extend((f'test ! -e {path}.paperos-disabled',
                            f'echo "{item["sha256"]}  {path}" | /dev/shm/paperos-backup-tools/busybox sha256sum -c -'))
        for name in ('otaupd', 'otav3'):
            actions.append(f'case "$(initctl status {name})" in *start/*) initctl stop {name} ;; esac')
        actions.extend(f'mv {item["path"]} {item["path"]}.paperos-disabled' for item in records)
        job_hash = hashlib.sha256(job).hexdigest()
        script = f'''set -eu
test ! -e /etc/upstart/paperos-devbridge.conf
test "$(cat /mnt/us/paperos/usb-debug/OWNER)" = paperos-usb-debug-v1
echo "{job_hash}  {ram}/paperos-devbridge.conf" | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
mntroot rw
trap 'sync; mntroot ro' EXIT
{chr(10).join(actions)}
cp {ram}/paperos-devbridge.conf /etc/upstart/paperos-devbridge.conf.paperos-new
chmod 644 /etc/upstart/paperos-devbridge.conf.paperos-new
mv /etc/upstart/paperos-devbridge.conf.paperos-new /etc/upstart/paperos-devbridge.conf
printf '%s\\n' paperos-usb-devbridge-v1 > /mnt/us/paperos/usb-debug/AUTOSTART
initctl reload-configuration
'''
        # Preserve restore information before the first device mutation.
        state = {'installed': False, 'ota_blocked': False, 'backup': str(directory),
                 'ota_files': records, 'job_sha256': job_hash}
        record_path.write_text(json.dumps(state, indent=2) + '\n')
        result = remote('/bin/sh -s', script.encode())
        (directory / 'install.log').write_bytes(result)
        proof = remote('test ! -e /usr/bin/otaupd && test ! -e /usr/bin/otav3 && grep " / ext3 ro," /proc/mounts && initctl status paperos-devbridge')
        (directory / 'verification.log').write_bytes(proof)
        state.update(installed=True, ota_blocked=True, autostart_debug=True, root_readonly_verified=True)
    record_path.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state), flush=True)


if __name__ == '__main__':
    main()

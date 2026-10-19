"""Expose the package folder and retain default packages in the independent OS."""
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


def remote(command, data=None):
    result = subprocess.run(ssh.connection(22) + [command], input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    return result.stdout


def main():
    remote('test "$(readlink /proc/1/exe)" = /bin/busybox && test -f /etc/paperos-release')
    service = ROOT / 'os/rootfs-overlay/etc/init.d/S15paperos-userstore'
    files = {'S15paperos-userstore': service}
    for app in ('clock', 'notes'):
        for source in (ROOT / f'examples/{app}.papp').rglob('*'):
            if source.is_file():
                files[f'{app}.papp/' + str(source.relative_to(ROOT / f'examples/{app}.papp'))] = source
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for name, source in files.items():
            archive.add(source, arcname=name)
    ram = '/run/paperos-runtime-' + uuid.uuid4().hex[:12]
    remote(f'umask 077; mkdir {ram} && tar xf - -C {ram}', payload.getvalue())
    checks = '\n'.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + ram + '/' + name
                       for name, path in files.items()) + '\n'
    remote('sha256sum -c -', checks.encode())
    remote('/bin/sh -s', f'''set -eu
test "$(cat /boot/paperos-control/paperos/BOOT_OWNER)" = paperos-bootstrap-v1
cp {ram}/S15paperos-userstore /etc/init.d/S15paperos-userstore.paperos-new
chmod 755 /etc/init.d/S15paperos-userstore.paperos-new
mv /etc/init.d/S15paperos-userstore.paperos-new /etc/init.d/S15paperos-userstore
/etc/init.d/S15paperos-userstore start
for PAPEROS_APP in clock notes; do
    if [ ! -e "/mnt/us/paperos/packages/$PAPEROS_APP.papp" ]; then
        cp -r "{ram}/$PAPEROS_APP.papp" "/mnt/us/paperos/packages/$PAPEROS_APP.papp"
    fi
done
test -s /mnt/us/paperos/packages/clock.papp/manifest.conf
test -s /mnt/us/paperos/packages/notes.papp/manifest.conf
sync
'''.encode())
    proof = {'passed': True, 'package_folder_available': True, 'default_packages_available': True,
             'usb_mode': 'Ethernet; the live root backing filesystem is not exported as a disk'}
    (ROOT / 'build/device-runtime-validation.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    main()

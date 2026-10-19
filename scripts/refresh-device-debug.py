"""Put the owned development payload outside USB storage, then renew its session."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
ssh = SourceFileLoader('paperos_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()


def remote(command, data=None):
    return subprocess.run(ssh.connection() + [command], input=data, capture_output=True, check=True).stdout


def main():
    state_path = ROOT / 'build/device-development-setup.json'
    state = json.loads(state_path.read_text())
    if not state['installed'] or not state['ota_blocked']:
        raise ValueError('The reversible development setup must be installed first')
    files = {'paperos-backup-tools': ROOT / 'dist/paperos-backup-tools',
             'launch-usb-debug.sh': ROOT / 'device-probe/bin/launch-usb-debug.sh',
             'run-usb-debug.sh': ROOT / 'device-probe/bin/run-usb-debug.sh',
             'paperos-devbridge.conf': ROOT / 'device-probe/paperos-devbridge.conf'}
    for name in ('dropbear', 'libc.so', 'authorized_keys', 'server_host_key'):
        files[name] = ROOT / 'build/usb-debug' / name
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode='w') as archive:
        for name, source in files.items():
            archive.add(source, arcname=name)
    destination = '/var/local/paperos-usb-debug'
    remote('test "$(id -u)" = 0 && test "$(cat /proc/bootmode)" = main && test -e /dev/shm/paperos-usb-debug/connected')
    remote(f'umask 077; test ! -e {destination} || test "$(cat {destination}/OWNER)" = paperos-usb-debug-v1; mkdir -p {destination}; /bin/busybox tar xf - -C {destination}', memory.getvalue())
    checks = '\n'.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + destination + '/' + n for n, p in files.items()) + '\n'
    remote('/dev/shm/paperos-backup-tools/busybox sha256sum -c -', checks.encode())
    script = f'''set -eu
test "$(head -n 1 /etc/upstart/paperos-devbridge.conf)" = '# paperos-usb-devbridge-v1'
printf '%s\\n' paperos-usb-debug-v1 > {destination}/OWNER
printf '%s\\n' paperos-usb-devbridge-v1 > {destination}/AUTOSTART
chmod 700 {destination}
chmod 600 {destination}/server_host_key {destination}/authorized_keys
mntroot rw
trap 'sync; mntroot ro' EXIT
cp {destination}/paperos-devbridge.conf /etc/upstart/paperos-devbridge.conf.paperos-new
chmod 644 /etc/upstart/paperos-devbridge.conf.paperos-new
mv /etc/upstart/paperos-devbridge.conf.paperos-new /etc/upstart/paperos-devbridge.conf
initctl reload-configuration
'''
    remote('/bin/sh -s', script.encode())
    waiter = '''#!/bin/sh
touch /dev/shm/paperos-usb-debug/return-to-usb
while [ -d /dev/shm/paperos-usb-debug/RUNNING ]; do /bin/busybox sleep 1; done
/bin/busybox sleep 5
PAPEROS_SOURCE=/var/local/paperos-usb-debug
export PAPEROS_SOURCE
exec /bin/sh "$PAPEROS_SOURCE/launch-usb-debug.sh"
'''
    remote('cat > /dev/shm/paperos-debug-renew.sh', waiter.encode())
    state.update(debug_payload_outside_usb_storage=True, debug_session_seconds=None,
                 debug_waits_for_explicit_restore=True,
                 job_sha256=hashlib.sha256(files['paperos-devbridge.conf'].read_bytes()).hexdigest())
    state_path.write_text(json.dumps(state, indent=2) + '\n')
    remote('/dev/shm/paperos-backup-tools/busybox setsid /bin/sh /dev/shm/paperos-debug-renew.sh </dev/null >/dev/shm/paperos-debug-renew.log 2>&1 &')
    print(json.dumps({'payload_verified': True, 'refresh_started': True, 'waits_for_explicit_restore': True}))


if __name__ == '__main__':
    main()

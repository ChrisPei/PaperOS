"""Hot-update the launcher and system keyboard after matching KT3 validation.

Only program/service/package files are replaced. App data, the boot wrapper,
kernel, partitions and running filesystem image remain in place.
"""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import time
import uuid
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path('/home/chris/kindle-build/output-kt3/target')
ssh = SourceFileLoader('paperos_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(command, data=None, check=True):
    reply = subprocess.run(ssh.connection(22) + [command], input=data, capture_output=True, timeout=40)
    if check and reply.returncode:
        raise RuntimeError('USB update failed: ' + (reply.stderr + reply.stdout).decode('utf-8', 'replace'))
    return reply


def main():
    proof = json.loads((ROOT / 'build/system-input-emulator-validation.json').read_text())
    if not proof['passed'] or not proof['system_input']['keyboard_closed_and_launcher_reacquired_touch']:
        raise ValueError('Matching keyboard/app handover validation is required')
    sources = {'/usr/bin/paperos': TARGET / 'usr/bin/paperos',
               '/usr/sbin/paperos-inputd': TARGET / 'usr/sbin/paperos-inputd',
               '/usr/bin/paperos-input': TARGET / 'usr/bin/paperos-input',
               '/etc/init.d/S55paperos-input': ROOT / 'os/rootfs-overlay/etc/init.d/S55paperos-input'}
    expected = proof['system_input']['program_sha256']
    for destination, source in sources.items():
        if source.is_symlink() or digest(source) != expected[destination]:
            raise ValueError('Program changed after emulator validation: ' + destination)
    remote('test "$(readlink /proc/1/exe)" = /bin/busybox && test -f /run/paperos/boot-confirmed && test "$(pidof paperos | wc -w)" -eq 1 && flock -n /var/lib/paperos/apps/.manager.lock true')
    token = uuid.uuid4().hex[:12]
    directory = ROOT / 'build' / ('input-runtime-install-' + token)
    directory.mkdir()
    ram = '/run/paperos-input-install-' + token
    backup = '/var/lib/paperos/system-backups/input-' + token
    records = []
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for destination, source in sources.items():
            name = source.name
            archive.add(source, arcname=name)
            present = remote('test -f ' + destination, check=False).returncode == 0
            row = {'destination': destination, 'name': name, 'sha256': digest(source), 'previously_present': present}
            if present:
                old = remote('cat ' + destination).stdout
                (directory / (name + '.previous')).write_bytes(old)
                row['previous_sha256'] = hashlib.sha256(old).hexdigest()
            records.append(row)
        for source in (ROOT / 'examples/input-demo.papp').rglob('*'):
            if source.is_file():
                archive.add(source, arcname='input-demo.papp/' + str(source.relative_to(ROOT / 'examples/input-demo.papp')))
    state = {'installed': False, 'records': records, 'device_backup': backup,
             'emulator_validation': proof['artifacts'], 'app_data_preserved': True}
    record_path = ROOT / 'build/system-input-device-validation.json'
    if record_path.is_file():
        (directory / 'prior-device-validation.json').write_bytes(record_path.read_bytes())
    record_path.write_text(json.dumps(state, indent=2) + '\n')
    remote(f'umask 077; mkdir {ram} && tar xf - -C {ram}', payload.getvalue())
    checks = '\n'.join(row['sha256'] + '  ' + ram + '/' + row['name'] for row in records) + '\n'
    remote('sha256sum -c -', checks.encode())
    backup_commands, replacements, restore = [], [], []
    for row in records:
        destination, name = row['destination'], row['name']
        if row['previously_present']:
            backup_commands.extend((f"echo '{row['previous_sha256']}  {destination}' | sha256sum -c -",
                                    f'cp -p {destination} {backup}/{name}'))
            restore.append(f'cp -p {backup}/{name} {destination}.input-restore; mv {destination}.input-restore {destination}')
        else:
            backup_commands.append(f'test ! -e {destination}')
            restore.append(f'rm -f {destination}')
        replacements.extend((f'cp {ram}/{name} {destination}.input-new',
                             f'chmod 755 {destination}.input-new', f'mv {destination}.input-new {destination}',
                             f"echo '{row['sha256']}  {destination}' | sha256sum -c -"))
    script = f'''set -eu
test "$(readlink /proc/1/exe)" = /bin/busybox
exec 8>/var/lib/paperos/apps/.manager.lock
flock -n 8
test "$(pidof paperos | wc -w)" -eq 1
PAPEROS_LAUNCHER=$(pidof paperos)
if [ -e /etc/init.d/S55paperos-input ]; then
    grep -q '^# paperos-input-service-v1$' /etc/init.d/S55paperos-input
    /etc/init.d/S55paperos-input stop
fi
mkdir -p {backup}
chmod 700 {backup}
{chr(10).join(backup_commands)}
PAPEROS_NOTE=/var/lib/paperos/apps/.data/org.paperos.notes/note.txt
PAPEROS_NOTE_HASH=absent
if [ -f "$PAPEROS_NOTE" ]; then PAPEROS_NOTE_HASH=$(sha256sum "$PAPEROS_NOTE"); fi
PAPEROS_FINISHED=0
rollback() {{
    if [ "$PAPEROS_FINISHED" != 1 ]; then
        {chr(10).join(restore)}
        sync
    fi
}}
trap rollback EXIT
{chr(10).join(replacements)}
if [ "$PAPEROS_NOTE_HASH" = absent ]; then test ! -f "$PAPEROS_NOTE"; else test "$PAPEROS_NOTE_HASH" = "$(sha256sum "$PAPEROS_NOTE")"; fi
mkdir -p /mnt/us/paperos/packages
if [ ! -e /mnt/us/paperos/packages/input-demo.papp ]; then cp -r {ram}/input-demo.papp /mnt/us/paperos/packages/input-demo.papp; fi
sync
kill -TERM "$PAPEROS_LAUNCHER"
PAPEROS_FINISHED=1
flock -u 8
exec 8>&-
/etc/init.d/S55paperos-input start
'''
    installed = remote('/bin/sh -s', script.encode())
    (directory / 'install.log').write_bytes(installed.stdout + installed.stderr)
    deadline = time.monotonic() + 25
    healthy = False
    while time.monotonic() < deadline:
        result = remote('test -S /run/paperos/input.sock && pidof paperos-inputd >/dev/null && '
                        'test "$(pidof paperos | wc -w)" -eq 1 && '
                        'test "$(readlink /proc/$(pidof paperos)/exe)" = /usr/bin/paperos', check=False)
        if result.returncode == 0:
            healthy = True
            break
        time.sleep(1)
    if not healthy:
        raise RuntimeError('Updated program files are installed, but the launcher/service needs investigation; original files are backed up')
    current = remote('sha256sum /usr/bin/paperos /usr/sbin/paperos-inputd /usr/bin/paperos-input /etc/init.d/S55paperos-input').stdout.decode()
    if {line.split()[1]: line.split()[0] for line in current.splitlines()} != expected:
        raise ValueError('Post-update program digest mismatch')
    running = remote('sha256sum /proc/$(pidof paperos)/exe').stdout.decode().split()[0]
    if running != expected['/usr/bin/paperos']:
        raise ValueError('Launcher process is not running the validated program')
    state.update(installed=True, service_started=True, launcher_resumed=True,
                 independent_system_kept_running=True, user_interaction_confirmation='pending')
    record_path.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({'installed': True, 'service_started': True, 'launcher_resumed': True,
                      'app_data_preserved': True, 'reboot_required': False}), flush=True)


if __name__ == '__main__':
    main()

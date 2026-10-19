"""Hot-update validated PaperOS programs and apps; preserve data and boot recovery."""
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import time
import uuid
from importlib.machinery import SourceFileLoader

ROOT = Path('/mnt/d/kindle')
ssh = SourceFileLoader('dashboard_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(command, data=None, check=True):
    result = subprocess.run(ssh.connection(22) + [command], input=data, capture_output=True, timeout=75)
    if check and result.returncode:
        raise RuntimeError((result.stderr + result.stdout).decode('utf-8', 'replace')[-3000:])
    return result


def main():
    proof = json.loads((ROOT / 'build/dashboard-emulator-validation.json').read_text())
    wifi = json.loads((ROOT / 'build/wifi-hardware-validation.json').read_text())
    image = json.loads((ROOT / 'build/dashboard-rootfs.json').read_text())
    backup = json.loads((ROOT / 'build/full-backup-state.json').read_text(encoding='utf-8-sig'))
    if not backup['complete'] or not proof['passed'] or not wifi['passed'] or proof['source_image_sha256'] != image['sha256']:
        raise ValueError('Matching full-backup, dashboard boot, and real-radio validation are required')
    expected = proof['dashboard']['program_sha256']
    records = image['records']
    for row in records:
        if digest(Path(row['source'])) != row['sha256']:
            raise ValueError('Source changed after image validation: ' + row['destination'])
        if row['destination'] in expected and row['sha256'] != expected[row['destination']]:
            raise ValueError('Binary changed after KT3 validation: ' + row['destination'])
    if wifi['script_sha256'] != expected['/etc/init.d/S45paperos-wifi']:
        raise ValueError('Radio startup script changed after hardware validation')
    remote('test "$(readlink /proc/1/exe)" = /bin/busybox && test -f /run/paperos/boot-confirmed && test "$(pidof paperos | wc -w)" -eq 1 && flock -n /var/lib/paperos/apps/.manager.lock true')
    token = uuid.uuid4().hex[:12]
    directory = ROOT / 'build' / ('dashboard-device-update-' + token)
    directory.mkdir()
    ram = '/run/paperos-dashboard-update-' + token
    saved = '/mnt/us/paperos/dashboard-backup-' + token
    program_rows = [r for r in records if not r['destination'].startswith('/var/lib/paperos/apps/')]
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for index, row in enumerate(program_rows):
            row['name'] = 'file-' + str(index)
            target = shlex.quote(row['destination'])
            present = remote('test -f ' + target, check=False).returncode == 0
            row['previously_present'] = present
            if present:
                previous = remote('cat ' + target).stdout
                (directory / (row['name'] + '.previous')).write_bytes(previous)
                row['previous_sha256'] = hashlib.sha256(previous).hexdigest()
            archive.add(row['source'], arcname=row['name'])
        for app in ('alarm', 'calendar', 'weather', 'mihome'):
            archive.add(ROOT / 'examples' / (app + '.papp'), arcname=app + '.papp')
    remote(f'umask 077; mkdir {ram} && tar xf - -C {ram}', payload.getvalue())
    checks = ''.join(row['sha256'] + '  ' + ram + '/' + row['name'] + '\n' for row in program_rows)
    remote('sha256sum -c -', checks.encode())
    state = {'installed': False, 'backup': saved, 'records': program_rows, 'emulator_validation': proof['artifacts'],
             'boot_chain_modified': False, 'app_data_preserved': True}
    record_path = ROOT / 'build/dashboard-device-validation.json'
    record_path.write_text(json.dumps(state, indent=2) + '\n')
    preparation, replacements, restore = [], [], []
    for row in program_rows:
        target, name = row['destination'], row['name']
        if row['previously_present']:
            preparation.extend((f"echo '{row['previous_sha256']}  {target}' | sha256sum -c -", f'cp -p {target} {saved}/{name}'))
            restore.extend((f'cp -p {saved}/{name} {target}.dashboard-restore', f'mv {target}.dashboard-restore {target}'))
        else:
            preparation.append(f'test ! -e {target}')
            restore.append(f'rm -f {target}')
        mode = '755' if target.startswith(('/usr/bin/', '/usr/sbin/', '/etc/init.d/')) else '644'
        replacements.extend((f'mkdir -p {Path(target).parent}', f'cp {ram}/{name} {target}.dashboard-new',
                             f'chmod {mode} {target}.dashboard-new', f'mv {target}.dashboard-new {target}',
                             f"echo '{row['sha256']}  {target}' | sha256sum -c -"))
    app_restore = []
    for app in ('alarm', 'calendar', 'weather', 'mihome', 'clock'):
        target = '/var/lib/paperos/apps/org.paperos.' + app
        hidden = '/var/lib/paperos/apps/.dashboard-held-' + token + '-' + app
        app_restore.extend((f'if [ -d {target} ]; then mv {target} {hidden}; fi',
                            f'if [ -d {saved}/apps/org.paperos.{app} ]; then cp -r {saved}/apps/org.paperos.{app} {target}; fi'))
    restore_script = '#!/bin/sh\nset -eu\n' + '\n'.join(restore + app_restore) + '\nsync\n'
    (directory / 'restore-programs.sh').write_text(restore_script)
    remote(f'mkdir -p {saved}; chmod 700 {saved}; cat > {saved}/restore-programs.sh', restore_script.encode())
    script = f'''set -eu
test "$(pidof paperos | wc -w)" -eq 1
chmod 755 {ram}/file-0
PAPEROS_OLD_LAUNCHER=$(pidof paperos)
PAPEROS_NOTE=/var/lib/paperos/apps/.data/org.paperos.notes/note.txt
PAPEROS_NOTE_HASH=absent
if [ -f "$PAPEROS_NOTE" ]; then PAPEROS_NOTE_HASH=$(sha256sum "$PAPEROS_NOTE"); fi
{chr(10).join(preparation)}
mkdir -p {saved}/apps
for PAPEROS_APP in alarm calendar weather mihome clock; do
    if [ -d /var/lib/paperos/apps/org.paperos."$PAPEROS_APP" ]; then
        cp -r /var/lib/paperos/apps/org.paperos."$PAPEROS_APP" {saved}/apps/
    fi
done
PAPEROS_DONE=0
rollback() {{
    if [ "$PAPEROS_DONE" != 1 ]; then
        if [ -f /etc/init.d/S60paperos-services ]; then sh /etc/init.d/S60paperos-services stop || true; fi
        sh {saved}/restore-programs.sh || true
    fi
}}
trap rollback EXIT
for PAPEROS_APP in alarm calendar weather mihome; do
    {ram}/file-0 --app-root /var/lib/paperos/apps --install {ram}/"$PAPEROS_APP".papp
done
if [ -f /var/lib/paperos/apps/org.paperos.clock/manifest.conf ]; then
    {ram}/file-0 --app-root /var/lib/paperos/apps --remove org.paperos.clock
fi
exec 8>/var/lib/paperos/apps/.manager.lock
flock -n 8
test "$(pidof paperos | wc -w)" -eq 1
{chr(10).join(replacements)}
if [ "$PAPEROS_NOTE_HASH" = absent ]; then test ! -e "$PAPEROS_NOTE"; else test "$PAPEROS_NOTE_HASH" = "$(sha256sum "$PAPEROS_NOTE")"; fi
sync
/etc/init.d/S60paperos-services start
test -S /run/paperos/services.sock
kill -TERM "$PAPEROS_OLD_LAUNCHER"
PAPEROS_DONE=1
flock -u 8
exec 8>&-
'''
    # The first validated program row is /usr/bin/paperos, intentionally used
    # before replacing the running launcher so widget manifests can be installed.
    if program_rows[0]['destination'] != '/usr/bin/paperos':
        raise ValueError('Unexpected payload ordering')
    installed = remote('/bin/sh -s', script.encode())
    (directory / 'install.log').write_bytes(installed.stdout + installed.stderr)
    healthy = False
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        reply = remote('test -S /run/paperos/services.sock && pidof paperos-services >/dev/null && pidof paperos-inputd >/dev/null && test "$(pidof paperos | wc -w)" -eq 1 && test "$(readlink /proc/$(pidof paperos)/exe)" = /usr/bin/paperos', check=False)
        if reply.returncode == 0:
            healthy = True
            break
        time.sleep(1)
    if not healthy:
        raise RuntimeError('Files are installed and backed up, but the updated UI/service requires investigation')
    current = remote('sha256sum ' + ' '.join(expected)).stdout.decode()
    if {line.split()[1]: line.split()[0] for line in current.splitlines()} != expected:
        raise ValueError('Post-update program checksum mismatch')
    if remote('sha256sum /proc/$(pidof paperos)/exe').stdout.decode().split()[0] != expected['/usr/bin/paperos']:
        raise ValueError('Old launcher process is still running')
    state.update(installed=True, launcher_resumed=True, service_running=True, reboot_required=False,
                 wifi_credentials_configured=False, on_device_interaction_confirmation='pending')
    record_path.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({key: state[key] for key in ('installed', 'launcher_resumed', 'service_running', 'app_data_preserved', 'reboot_required')}), flush=True)


if __name__ == '__main__':
    main()

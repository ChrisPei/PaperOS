"""Install the file-backed, failure-recovering PID 1 bootstrap over pinned USB SSH.

The independent root remains a regular file in the existing userstore. Retain
the exact stock init; never flash a partition, bootloader, boot mode or IDME.
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
STATE = ROOT / 'build/device-bootstrap-state.json'
OWNER = 'paperos-bootstrap-v1'
CONTROL = '/mnt/us/paperos'
ssh = SourceFileLoader('paperos_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def remote(command, data=None, stdin=None, port=2222, timeout=120):
    reply = subprocess.run(ssh.connection(port) + [command], input=data, stdin=stdin,
                           capture_output=True, timeout=timeout)
    if reply.returncode:
        raise RuntimeError(f'Device SSH exit {reply.returncode}: ' + reply.stderr.decode('utf-8', 'replace'))
    return reply.stdout


def shell(script, port=2222):
    return remote('/bin/sh -s', script.encode(), port=port)


def save(state):
    STATE.write_text(json.dumps(state, indent=2) + '\n')


def inputs():
    backup = json.loads((ROOT / 'build/full-backup-state.json').read_text(encoding='utf-8-sig'))
    state = json.loads((ROOT / 'build/device-main-rootfs.json').read_text())
    proof = json.loads((ROOT / 'build/bootstrap-validation.json').read_text())
    image = Path(state['image'])
    if (not backup['complete'] or backup['emmc_bytes'] != 3909091328 or
        not proof['passed'] or not proof['missing_image_returns_to_stock_init'] or
        not proof['automatic_boot_after_restart'] or not proof['guest_public_key_ssh_verified']):
        raise ValueError('Complete backup and successful independent boot/restart/fallback validation are required')
    if (image.is_symlink() or not image.resolve().is_relative_to((ROOT / 'build').resolve()) or
        image.stat().st_size != 256 * 1024 * 1024 or digest(image) != state['sha256'] or
        state['sha256'] != proof['source_image_sha256'] or
        digest(ROOT / 'dist/paperos-bootstrap') != proof['bootstrap_sha256'] or
        digest(ROOT / 'device-probe/paperos-init') != proof['init_wrapper_sha256']):
        raise ValueError('Deployment inputs changed after emulator validation')
    return state, image, proof


def stock_ready():
    return shell('''set -eu
test "$(id -u)" = 0
test "$(cat /proc/bootmode)" = main
test "$(readlink /proc/1/exe)" = /sbin/init.exe
test -e /dev/shm/paperos-usb-debug/connected
test ! -e /usr/bin/otaupd
test ! -e /usr/bin/otav3
grep ' / ext3 ro,' /proc/mounts
''')


def stage():
    image_state, image, proof = inputs()
    stock_ready()
    state = json.loads(STATE.read_text()) if STATE.exists() else {'installed': False}
    shell(f'''set -eu
test ! -e {CONTROL}/BOOT_OWNER || test "$(cat {CONTROL}/BOOT_OWNER)" = {OWNER}
test ! -e {CONTROL}/system.ext3 || test -e {CONTROL}/BOOT_OWNER
test ! -e {CONTROL}/boot.enable
mkdir -p {CONTROL}
printf '%s\\n' {OWNER} > {CONTROL}/BOOT_OWNER
sync
''')
    available = int(remote('df -k /mnt/us').decode().splitlines()[-1].split()[3]) * 1024
    if available < image.stat().st_size + 32 * 1024 * 1024:
        raise ValueError('Insufficient userstore space for the independent filesystem')
    state.update(image_staged=False, image_sha256=image_state['sha256'],
                 image_bytes=image.stat().st_size, changes_idme=False, flashes_partitions=False,
                 emulator_validation=proof, root_image=str(image))
    save(state)
    print('Uploading the verified independent filesystem as a regular file.', flush=True)
    with image.open('rb') as file:
        remote(f'umask 077; cat > {CONTROL}/system.ext3.paperos-new', stdin=file, timeout=240)
    shell(f'''set -eu
echo '{image_state['sha256']}  {CONTROL}/system.ext3.paperos-new' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
sync
mv {CONTROL}/system.ext3.paperos-new {CONTROL}/system.ext3
sync
''')
    state['image_staged'] = True
    save(state)
    print(json.dumps({'image_staged': True, 'bytes': image.stat().st_size, 'sha256': image_state['sha256']}), flush=True)


def install():
    image_state, image, proof = inputs()
    stock_ready()
    state = json.loads(STATE.read_text())
    if not state['image_staged'] or state['image_sha256'] != image_state['sha256']:
        raise ValueError('The exact verified image must be staged first')
    original = subprocess.run(['debugfs', '-R', 'cat /sbin/init',
                               str(ROOT / 'build/device-backup-inspection/mmcblk0p1.img')],
                              check=True, capture_output=True).stdout
    if not original.startswith(b'#!') or len(original) != 1360:
        raise ValueError('Unexpected stock init in the verified full backup')
    original_hash = hashlib.sha256(original).hexdigest()
    actual = remote('cat /sbin/init')
    wrapper = ROOT / 'device-probe/paperos-init'
    if actual == wrapper.read_bytes():
        if remote('cat /sbin/init.paperos-stock') != original:
            raise ValueError('Retained stock init does not match the full backup')
    elif actual != original:
        raise ValueError('Existing init differs from the full backup; refusing to replace it')
    directory = ROOT / 'build' / ('device-bootstrap-backup-' + uuid.uuid4().hex[:12])
    directory.mkdir()
    (directory / 'stock-init').write_bytes(original)
    state.update(installed=False, init_backup=str(directory), stock_init_sha256=original_hash)
    save(state)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for name, path in (('paperos-bootstrap', ROOT / 'dist/paperos-bootstrap'),
                           ('paperos-init', wrapper), ('stock-init', directory / 'stock-init')):
            archive.add(path, arcname=name)
    ram = '/dev/shm/paperos-bootstrap-install-' + uuid.uuid4().hex[:12]
    remote(f'umask 077; mkdir {ram} && /bin/busybox tar xf - -C {ram}', data=payload.getvalue())
    install_script = f'''set -eu
test "$(cat {CONTROL}/BOOT_OWNER)" = {OWNER}
test ! -e {CONTROL}/boot.enable
echo '{image_state['sha256']}  {CONTROL}/system.ext3' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
echo '{proof['bootstrap_sha256']}  {ram}/paperos-bootstrap' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
echo '{proof['init_wrapper_sha256']}  {ram}/paperos-init' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
echo '{original_hash}  {ram}/stock-init' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
chmod 755 {ram}/paperos-bootstrap
test "$({ram}/paperos-bootstrap --check)" = paperos-bootstrap-v1
if [ -e /sbin/init.paperos-stock ]; then
    echo '{original_hash}  /sbin/init.paperos-stock' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
else
    echo '{original_hash}  /sbin/init' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
fi
mntroot rw
trap 'sync; mntroot ro' EXIT
if [ ! -e /sbin/init.paperos-stock ]; then
    cp /sbin/init /sbin/init.paperos-stock.paperos-new
    chmod 755 /sbin/init.paperos-stock.paperos-new
    mv /sbin/init.paperos-stock.paperos-new /sbin/init.paperos-stock
fi
cp {ram}/paperos-bootstrap /sbin/paperos-bootstrap.paperos-new
chmod 755 /sbin/paperos-bootstrap.paperos-new
mv /sbin/paperos-bootstrap.paperos-new /sbin/paperos-bootstrap
mkdir -p /mnt/paperos-boot /mnt/paperos-root
sync
cp {ram}/paperos-init /sbin/init.paperos-new
chmod 755 /sbin/init.paperos-new
mv /sbin/init.paperos-new /sbin/init
echo '{proof['init_wrapper_sha256']}  /sbin/init' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
echo '{original_hash}  /sbin/init.paperos-stock' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
echo '{proof['bootstrap_sha256']}  /sbin/paperos-bootstrap' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
'''
    (directory / 'install.log').write_bytes(shell(install_script))
    remote('grep " / ext3 ro," /proc/mounts')
    state.update(installed=True, root_readonly_verified=True,
                 bootstrap_sha256=proof['bootstrap_sha256'], init_wrapper_sha256=proof['init_wrapper_sha256'])
    save(state)
    print(json.dumps({'installed': True, 'retained_stock_init': True, 'boot_enabled': False}), flush=True)


def activate():
    inputs()
    stock_ready()
    state = json.loads(STATE.read_text())
    if not state['installed']:
        raise ValueError('Bootstrap installation must be verified first')
    # A root filesystem changes during normal operation (journal, notes, seed).
    # The initial full-file digest is required until its first verified boot.
    image_check = (f"test -f {CONTROL}/system.ext3 && test ! -L {CONTROL}/system.ext3" if
                   state.get('has_booted_hardware') else
                   f"echo '{state['image_sha256']}  {CONTROL}/system.ext3' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -")
    output = shell(f'''set -eu
test "$(cat {CONTROL}/BOOT_OWNER)" = {OWNER}
{image_check}
echo '{state['init_wrapper_sha256']}  /sbin/init' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
echo '{state['stock_init_sha256']}  /sbin/init.paperos-stock' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
echo 'b43461182e3b490879bcb7cea9f043cf64af9fa509d204d8f27f54d00f16082f  /etc/upstart/shutdown.conf' | /dev/shm/paperos-backup-tools/busybox sha256sum -c -
test ! -e /etc/upstart/shutdown.conf.paperos-original
printf '%s\\n' trial > {CONTROL}/boot.mode
printf '%s\\n' paperos-boot-v1 > {CONTROL}/boot.enable.new
sync
mv {CONTROL}/boot.enable.new {CONTROL}/boot.enable
sync
/dev/shm/paperos-backup-tools/busybox setsid /bin/sh -c '/bin/busybox sleep 3; /sbin/shutdown -r now' </dev/null >/dev/shm/paperos-bootstrap-reboot.log 2>&1 &
''')
    state.update(trial_boot_requested=True, hardware_boot_verified=False)
    save(state)
    print(json.dumps({'trial_boot_requested': True, 'fallback_unless_confirmed': True}), flush=True)


def confirm():
    state = json.loads(STATE.read_text())
    proof = shell('''set -eu
test "$(readlink /proc/1/exe)" = /bin/busybox
test -f /etc/paperos-release
grep '^/dev/loop[0-9]* / ext3 ' /proc/mounts
test -z "$(grep ' /old-root ' /proc/mounts)"
test -c /dev/fb0
test -c /dev/input/event0
pidof paperos >/dev/null
pidof dropbear >/dev/null
test ! -e /boot/paperos-control/paperos/boot.enable
/usr/sbin/paperos-ime nihao | grep 'commit=你好'
printf '%s\\n' automatic > /boot/paperos-control/paperos/boot.mode
mkdir -p /run/paperos
touch /run/paperos/boot-confirmed
sleep 3
test -f /boot/paperos-control/paperos/boot.enable
sync
''', port=22)
    (ROOT / 'build/device-bootstrap-hardware-proof.txt').write_bytes(proof)
    state.update(hardware_boot_verified=True, independent_pid1_and_root=True,
                 automatic_boot_enabled=True, trial_boot_requested=False, has_booted_hardware=True)
    save(state)
    print(json.dumps({'hardware_boot_verified': True, 'automatic_boot_enabled': True,
                      'original_chinese_input_engine': True}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('stage', 'install', 'activate', 'confirm'))
    args = parser.parse_args()
    globals()[args.action]()


if __name__ == '__main__':
    main()

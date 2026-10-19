"""Validate real PID 1/root replacement and fallback on a synthetic KT3 disk.

Only public stock firmware and a newly owned virtual disk are booted. Device
account data and the physical USB/eMMC device are never used by this test.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
WORK = Path('/home/chris/kindle-build')
PUBLIC = WORK / 'recovery-kt3'
control = SourceFileLoader('kt3_console', str(ROOT / 'scripts/kt3-console.py')).load_module()


def run(*arguments):
    return subprocess.run(arguments, capture_output=True, text=True, check=True)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--system-input', action='store_true')
    parser.add_argument('--dashboard', action='store_true')
    args = parser.parse_args()
    if not args.image.is_file() or args.image.is_symlink() or args.image.stat().st_size != 256*1024*1024:
        raise ValueError('Expected the private 256 MiB regular filesystem image')
    directory = WORK / ('bootstrap-validation-' + uuid.uuid4().hex[:12])
    directory.mkdir()
    payload = directory / 'paperos'
    payload.mkdir()
    image = payload / 'system.ext3'
    shutil.copyfile(args.image, image)
    env = directory / 'paperos.env'
    env.write_text(run('debugfs', '-R', 'cat /etc/paperos.env', str(image)).stdout + '\nPAPEROS_EMULATOR=1\nPAPEROS_USB_EMULATOR=1\n')
    for action in ('rm /etc/paperos.env', f'write {env} /etc/paperos.env', 'set_inode_field /etc/paperos.env mode 0100600'):
        run('debugfs', '-w', '-R', action, str(image))
    (payload / 'boot.enable').write_text('paperos-boot-v1\n')
    (payload / 'boot.mode').write_text('trial\n')
    if args.system_input:
        shutil.copytree(ROOT / 'examples/input-demo.papp', payload / 'packages/input-demo.papp')
    oldroot = directory / 'stock.ext3'
    shutil.copyfile(PUBLIC / 'rootfs.img', oldroot)
    original = run('debugfs', '-R', 'cat /sbin/init', str(oldroot)).stdout
    stock_init = directory / 'stock-init'
    stock_init.write_text(original.replace('\n', '\necho PAPEROS_STOCK_FALLBACK\n', 1))
    instructions = directory / 'stock.debugfs'
    instructions.write_text('\n'.join((
        'mkdir /mnt/paperos-boot', 'mkdir /mnt/paperos-root',
        'rm /sbin/init', f'write {ROOT / "device-probe/paperos-init"} /sbin/init',
        'set_inode_field /sbin/init mode 0100755',
        f'write {stock_init} /sbin/init.paperos-stock', 'set_inode_field /sbin/init.paperos-stock mode 0100755',
        f'write {ROOT / "dist/paperos-bootstrap"} /sbin/paperos-bootstrap', 'set_inode_field /sbin/paperos-bootstrap mode 0100755')) + '\n')
    run('debugfs', '-w', '-f', str(instructions), str(oldroot))
    repair = subprocess.run(['e2fsck', '-f', '-y', str(oldroot)], capture_output=True, text=True)
    (directory / 'stock-e2fsck.log').write_text(repair.stdout + repair.stderr)
    if repair.returncode not in (0, 1):
        raise RuntimeError(repair.stdout + repair.stderr)
    run('e2fsck', '-f', '-n', str(oldroot))
    for source, destination in ((ROOT / 'dist/paperos-bootstrap', '/sbin/paperos-bootstrap'),
                                (ROOT / 'device-probe/paperos-init', '/sbin/init'),
                                (stock_init, '/sbin/init.paperos-stock')):
        check = directory / 'file-check'
        run('debugfs', '-R', f'dump {destination} {check}', str(oldroot))
        if digest(check) != digest(source):
            raise ValueError('Stock test fixture copy failed: ' + destination)
        check.unlink()
    sys.path.insert(0, str(ROOT / 'tools/eink-emulator'))
    from eink_emulator.images import imx6_mmc
    disk = directory / 'disk.img'
    imx6_mmc.build(disk, PUBLIC / 'imx6sl_heisenberg/uImage', oldroot,
                  userstore=payload, layout='heisenberg')
    inspection = ROOT / 'build/device-backup-inspection'
    tree = (inspection / 'main.dtb').read_bytes()
    kernel = inspection / 'kernel-0005a000.uimage'
    with disk.open('r+b') as file:
        file.seek(0x41000)
        file.write(tree + bytes(0x19000-len(tree)) + kernel.read_bytes())
    # An ephemeral, loopback-only forward exercises the guest's real ARM SSH server.
    reservation = socket.socket()
    reservation.bind(('127.0.0.1', 0))
    port = reservation.getsockname()[1]
    reservation.close()
    reservation = socket.socket()
    reservation.bind(('127.0.0.1', 0))
    tls_port = reservation.getsockname()[1]
    reservation.close()
    known = directory / 'known_hosts'
    known.write_text((ROOT / 'build/usb-debug/known_hosts').read_text().replace('[169.254.28.2]:2222', '[127.0.0.1]:' + str(port)))
    key = directory / 'client-key'
    shutil.copyfile(ROOT / 'build/usb-debug/client_ed25519', key)
    key.chmod(0o600)
    transport = ['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                 '-o', 'UserKnownHostsFile=' + str(known), '-o', 'ConnectTimeout=3',
                 '-o', 'ControlMaster=auto', '-o', 'ControlPersist=15', '-o', 'ControlPath=' + str(directory / 'ssh-control'),
                 '-i', str(key), '-p', str(port), 'root@127.0.0.1']

    def ssh(command, check=True):
        reply = subprocess.run(transport + [command], capture_output=True, text=True, timeout=20)
        if check and reply.returncode:
            raise RuntimeError(f'Guest SSH exit {reply.returncode}: {reply.stderr.strip()}\n{reply.stdout.strip()}')
        return reply

    def start(index):
        for name in ('serial.sock', 'control.sock'):
            (directory / name).unlink(missing_ok=True)
        run(str(WORK / 'qemu-eink/build/qemu-system-arm'), '-name', 'PaperOS-Independent-Boot-Test',
            '-machine', 'imx6sl-eanab,idme-serial=G000K90000000001', '-m', '512M',
            '-bios', str(PUBLIC / 'imx6sl_heisenberg/u-boot.bin'),
            '-drive', f'file={disk},if=sd,index=1,format=raw',
            '-chardev', f'socket,id=serial0,path={directory}/serial.sock,server=on,wait=off,logfile={directory}/serial-{index}.log',
            '-serial', 'chardev:serial0', '-qmp', f'unix:{directory}/control.sock,server=on,wait=off',
            '-display', 'none', '-monitor', 'none', '-nic', 'none',
            '-netdev', f'user,id=usb,net=169.254.28.0/24,host=169.254.28.1,hostfwd=tcp:127.0.0.1:{port}-169.254.28.2:22,hostfwd=tcp:127.0.0.1:{tls_port}-169.254.28.2:8765,restrict=on',
            '-object', f'filter-dump,id=usb-capture,netdev=usb,file={directory}/usb-{index}.pcap',
            '-global', 'usb-chipidea.netdev=usb', '-no-reboot', '-daemonize', '-pidfile', str(directory / 'qemu.pid'))
        return control.Console(directory)

    def stop(console):
        console.close()
        subprocess.run(transport[:-1] + ['-O', 'exit', transport[-1]], capture_output=True, timeout=5)
        try:
            control.qmp(directory, 'quit')
        except (OSError, ValueError):
            pass
        time.sleep(0.4)

    def ready(console, index):
        console.send(b'root\n')
        console.receive(b'# ', 10)
        console.send(b'stty -echo\n')
        console.receive(b'# ', 5)
        (directory / f'network-start-{index}.txt').write_text(console.command('sleep 2; ping -c 1 -W 2 169.254.28.1; netstat -lnt; cat /var/log/messages | tail -n 15'))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if ssh('true', check=False).returncode == 0:
                return
            time.sleep(0.5)
        raise RuntimeError('Guest SSH did not become ready after USB configuration')

    def wait_reboot(console):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                chunk = console.socket.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                return
            console.transcript.extend(chunk)
        raise TimeoutError('The guest did not finish its normal reboot: ' + console.transcript[-1500:].decode('utf-8', 'replace'))

    result = {'passed': False, 'scope': 'synthetic file-backed emulator only', 'artifacts': str(directory),
              'bootstrap_sha256': digest(ROOT / 'dist/paperos-bootstrap'),
              'init_wrapper_sha256': digest(ROOT / 'device-probe/paperos-init'),
              'source_image_sha256': digest(args.image), 'kernel_sha256': digest(kernel)}
    console = None
    logged_in_console = None
    try:
        console = start(1)
        console.receive(b'login:', 120, forbidden=b'PAPEROS_STOCK_FALLBACK')
        ready(console, 1)
        logged_in_console = console
        details = ssh('cat /etc/paperos-release; readlink /proc/1/exe; cat /proc/mounts; pidof paperos; test ! -e /boot/paperos-control/paperos/boot.enable').stdout
        if '/bin/busybox' not in details or '/dev/loop' not in details or '/old-root ' in details:
            raise ValueError('PID 1/root replacement was not proven: ' + details[-1600:])
        result.update(independent_pid1_and_root=True, stock_root_detached=True,
                      guest_public_key_ssh_verified=True, boot_request_cleared=True)
        candidate = ssh('/usr/sbin/paperos-ime nihao').stdout
        if 'commit=你好' not in candidate:
            raise ValueError('Original Chinese engine failed after independent boot')
        result['original_chinese_input_engine'] = True
        if args.system_input:
            validation = SourceFileLoader('paperos_input_validation', str(ROOT / 'scripts/system-input-validation.py')).load_module()
            result['system_input'] = validation.validate(directory, ssh, transport, control.qmp, console)
        if args.dashboard:
            ssh('printf "automatic\\n" > /boot/paperos-control/paperos/boot.mode; touch /run/paperos/boot-confirmed')
            validation = SourceFileLoader('paperos_dashboard_validation', str(ROOT / 'scripts/dashboard-validation.py')).load_module()
            result['dashboard'] = validation.validate(directory, ssh, control.qmp, console, tls_port)
        ssh('mkdir -p /run/paperos; printf "automatic\\n" > /boot/paperos-control/paperos/boot.mode; touch /run/paperos/boot-confirmed; sleep 2; test -f /boot/paperos-control/paperos/boot.enable; sync')
        result['confirmed_boot_rearmed'] = True
        ssh('reboot', check=False)
        wait_reboot(console)
        stop(console)
        console = start(2)
        console.receive(b'login:', 120, forbidden=b'PAPEROS_STOCK_FALLBACK')
        ready(console, 2)
        logged_in_console = console
        ssh('sleep 5; test -f /boot/paperos-control/paperos/boot.enable; test -f /run/paperos/boot-confirmed')
        result['automatic_boot_after_restart'] = True
        # A missing image must clear the request and enter the retained stock init.
        ssh('mv /boot/paperos-control/paperos/system.ext3 /boot/paperos-control/paperos/system-held.ext3; sync; reboot', check=False)
        wait_reboot(console)
        stop(console)
        console = start(3)
        fallback = console.receive(b'PAPEROS_STOCK_FALLBACK', 120)
        if 'open independent filesystem' not in fallback:
            raise ValueError('The missing-image failure path was not exercised')
        result.update(missing_image_returns_to_stock_init=True, passed=True)
        print(json.dumps(result), flush=True)
    except Exception as error:
        result['error'] = str(error)
        if console and b'login:' in console.transcript:
            try:
                if logged_in_console is not console:
                    console.send(b'root\n')
                    console.receive(b'# ', 10)
                    console.send(b'stty -echo\n')
                    console.receive(b'# ', 5)
                diagnostics = console.command('ip address; netstat -lnt; ps; ls -ld /root /root/.ssh; ls -l /root/.ssh/authorized_keys; cat /var/log/messages | tail -n 30')
                (directory / 'failure-diagnostics.txt').write_text(diagnostics)
                result['diagnostics'] = diagnostics[-5000:]
            except Exception as diagnostic_error:
                result['diagnostics_error'] = str(diagnostic_error)
        print(json.dumps(result), flush=True)
        raise
    finally:
        if console:
            stop(console)
        (ROOT / 'build/bootstrap-validation.json').write_text(json.dumps(result, indent=2) + '\n')
        if args.system_input:
            (ROOT / 'build/system-input-emulator-validation.json').write_text(json.dumps(result, indent=2) + '\n')
        if args.dashboard:
            (ROOT / 'build/dashboard-emulator-validation.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()

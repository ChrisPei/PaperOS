"""Boot a 64 MiB PaperOS recovery filesystem on backed-up KT3 kernels.

Every write targets regular files in a fresh WSL emulator directory. Device
identity is synthetic; no original root filesystem or account data is booted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
WORK = Path('/home/chris/kindle-build')
INSPECTION = ROOT / 'build/device-backup-inspection'
REFERENCE = WORK / 'recovery-kt3/imx6sl_heisenberg'
SIZE = 64 * 1024 * 1024


def run(*arguments):
    return subprocess.run(arguments, check=True, text=True, capture_output=True)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', choices=('diags', 'main'), default='diags')
    parser.add_argument('--image', type=Path)
    parser.add_argument('--probe-wifi', action='store_true')
    args = parser.parse_args()
    proof = json.loads((INSPECTION / 'inspection.json').read_text())
    if not proof['backup_bytes_verified'] or not all(item['passed'] for item in proof['filesystems']):
        raise ValueError('A verified device backup is required')
    kernel_index = 1 if args.kernel == 'diags' else 0
    offset = proof['kernels'][kernel_index]['offset']
    kernel = INSPECTION / f'kernel-{offset:08x}.uimage'
    dtb = INSPECTION / f'{args.kernel}.dtb'
    if digest(kernel) != proof['kernels'][kernel_index]['sha256']:
        raise ValueError('Backed-up kernel checksum changed')
    directory = WORK / ('recovery-boot-validation-' + uuid.uuid4().hex[:12])
    directory.mkdir()
    image = directory / 'recovery.ext3'
    source_image=args.image or ROOT / 'dist/paperos-kt3-rootfs.ext3'
    if source_image.is_symlink() or not source_image.is_file() or source_image.stat().st_size not in (SIZE,256*1024*1024):
        raise ValueError('Expected a regular 64/256 MiB PaperOS filesystem image')
    shutil.copyfile(source_image, image)
    run('e2fsck', '-f', '-y', str(image))
    run('resize2fs', str(image), '64M')
    with image.open('r+b') as file:
        file.truncate(SIZE)
    run('e2fsck', '-f', '-n', str(image))
    env = directory / 'paperos.env'
    env.write_text(run('debugfs', '-R', 'cat /etc/paperos.env', str(image)).stdout + '\nPAPEROS_EMULATOR=1\n')
    for operation in ('rm /etc/paperos.env', f'write {env} /etc/paperos.env'):
        run('debugfs', '-w', '-R', operation, str(image))
    debug_payload = ROOT / 'build/usb-debug'
    debug_test = (debug_payload / 'manifest.json').is_file()
    if debug_test:
        run('debugfs', '-w', '-R', 'mkdir /debug-auth', str(image))
        for filename, destination in (('authorized_keys', '/debug-auth/authorized_keys'), ('server_host_key', '/debug-hostkey')):
            run('debugfs', '-w', '-R', f'write {debug_payload / filename} {destination}', str(image))
            run('debugfs', '-w', '-R', f'set_inode_field {destination} mode 0100600', str(image))
    # Preserve the stock on-disk contract: DTB at e41000, uImage at e5a000.
    bundle = directory / 'kernel-bundle.bin'
    tree = dtb.read_bytes()
    if len(tree) > 0x19000:
        raise ValueError('Device tree exceeds its reserved slot')
    bundle.write_bytes(tree + bytes(0x19000 - len(tree)) + kernel.read_bytes())
    disk = directory / 'disk.img'
    sys.path.insert(0, str(ROOT / 'tools/eink-emulator'))
    from eink_emulator.images import imx6_mmc
    imx6_mmc.build(disk, REFERENCE / 'uImage', image, layout='heisenberg')
    if not disk.is_file() or disk.is_symlink() or disk.resolve().parent != directory.resolve():
        raise ValueError('Expected a regular virtual disk inside the test directory')
    with disk.open('r+b') as file:
        file.seek(987136 * 512)
        file.write(image.read_bytes())
        file.seek(0xe41000)
        file.write(bundle.read_bytes())
    qemu = WORK / 'qemu-eink/build/qemu-system-arm'
    run(str(qemu), '-name', 'PaperOS-Recovery-Test', '-machine', 'imx6sl-eanab,idme-serial=G000K90000000001',
        '-m', '512M', '-bios', str(REFERENCE / 'u-boot.bin'),
        '-drive', f'file={disk},if=sd,index=1,format=raw',
        '-chardev', f'socket,id=serial0,path={directory}/serial.sock,server=on,wait=off,logfile={directory}/serial.log',
        '-serial', 'chardev:serial0', '-monitor', 'none', '-qmp', f'unix:{directory}/control.sock,server=on,wait=off',
        '-display', 'none', '-nic', 'none',
        '-netdev', 'user,id=wifi,restrict=on', '-global', 'bcm43430-sdio.netdev=wifi',
        '-no-reboot', '-daemonize', '-pidfile', str(directory / 'qemu.pid'))
    console = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    console.connect(str(directory / 'serial.sock'))
    console.settimeout(0.5)
    transcript = bytearray()
    pending = bytearray()

    def receive(marker, timeout=60):
        received = bytearray(pending)
        pending.clear()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if marker in received:
                return received.decode('utf-8', 'replace')
            try:
                data = console.recv(65536)
            except socket.timeout:
                continue
            if not data:
                raise RuntimeError('Recovery console disconnected')
            transcript.extend(data)
            received.extend(data)
            if marker in received:
                return received.decode('utf-8', 'replace')
        raise TimeoutError(received[-1500:].decode('utf-8', 'replace'))

    def send(data):
        # Drain output while transmitting so asynchronous driver logs cannot
        # deadlock the two directions of the serial socket.
        for position in range(0, len(data), 4):
            readable, _, _ = select.select([console], [], [], 0)
            if readable:
                chunk = console.recv(65536)
                if not chunk:
                    raise RuntimeError('Recovery console disconnected')
                transcript.extend(chunk)
                pending.extend(chunk)
            console.sendall(data[position:position + 4])
            time.sleep(0.03)

    def command(text):
        marker = 'PAPEROS_RC_' + uuid.uuid4().hex[:12]
        send((text + f'; PAPEROS_RC=$?; printf "\\n{marker}:%s:END\\n" "$PAPEROS_RC"\n').encode())
        result = receive(b':END')
        match = re.search(re.escape(marker) + r':(\d+):END', result)
        if not match or int(match[1]):
            raise RuntimeError(result[-2000:])
        if '# ' not in result.split(marker,1)[1]:
            receive(b'# ',10)
        return result.split(marker)[0]

    result = {'passed': False, 'kernel_source': args.kernel, 'kernel_sha256': digest(kernel),
              'rootfs_bytes': SIZE, 'rootfs_sha256': digest(image), 'artifacts': str(directory),
              'source_image_sha256': digest(source_image),
              'wifi_probe_requested': args.probe_wifi,
              'scope': 'file-backed emulator only; synthetic identity; no physical writes'}
    try:
        receive(b'Hit any key to stop autoboot:', 30)
        send(b' ')
        receive(b'uboot >', 10)
        send(b'run diags_boot\n')
        receive(b'login:', 120)
        send(b'root\n')
        receive(b'# ', 15)
        send(b'stty -echo\n')
        receive(b'# ', 5)
        details = command('uname -a; cat /proc/cmdline; cat /proc/modules; cat /sys/class/graphics/fb0/name; test -c /dev/fb0; test -c /dev/input/event0; pidof paperos')
        if 'root=/dev/mmcblk0p2' not in details or 'mxc_epdc_fb' not in details or 'zforce2' not in details:
            raise ValueError('Recovery did not boot from p2 with the required display/touch drivers')
        result['runtime'] = details.strip()
        if args.image:
            candidate = command('/usr/sbin/paperos-ime nihao')
            if '0\t你好' not in candidate or 'commit=你好' not in candidate:
                raise ValueError('Original input engine failed on the backed-up kernel')
            result['original_chinese_input_engine_on_device_kernel'] = True
            applications = command('/usr/bin/paperos --list-apps; pidof dropbear')
            if 'org.paperos.clock' not in applications or 'org.paperos.notes' not in applications:
                raise ValueError('Default standalone applications are missing')
            result['standalone_applications_and_boot_ssh_service'] = True
            modules = command('modprobe libcomposite; modprobe g_ether > /tmp/gadget.log 2>&1 || true; cat /tmp/gadget.log; dmesg | tail -n 15')
            if 'Unknown symbol' in modules:
                raise ValueError('USB modules are incompatible with the backed-up kernel')
            result['usb_modules_have_no_unresolved_symbols'] = True
            command('test -s /lib/modules/3.10.53-lab126/extra/dhd.ko && test -s /opt/brcm_4343w/wifi/firmware/fw_bcmdhd_sr.bin && test -s /opt/brcm_4343w/wifi/nvram/nvram.txt')
            result['wifi_files_present'] = True
            result['wifi_radio_connection_verified'] = False
        if debug_test:
            command('/lib/libc.so --library-path /lib /usr/sbin/dropbear -F -E -j -k -m -D /debug-auth -r /debug-hostkey -p 127.0.0.1:2222 > /tmp/ssh-test.log 2>&1 & PAPEROS_SSH=$!; sleep 1; kill -0 "$PAPEROS_SSH"; PAPEROS_STATUS=$?; cat /tmp/ssh-test.log; kill "$PAPEROS_SSH"; test "$PAPEROS_STATUS" = 0')
            result['ssh_server_started_with_ram_debug_options'] = True
            (debug_payload / 'validation.json').write_text(json.dumps({
                'passed': True, 'kernel': '3.10.53-lab126',
                'dropbear_sha256': digest(debug_payload / 'dropbear'),
                'libc_sha256': digest(debug_payload / 'libc.so'),
                'artifacts': str(directory), 'scope': 'server startup/options on file-backed emulator'}, indent=2) + '\n')
        if args.probe_wifi:
            wifi = command('modprobe dhd > /tmp/wifi-test.log 2>&1 || true; cat /tmp/wifi-test.log; dmesg | tail -n 30')
            if 'Unknown symbol' in wifi:
                raise ValueError('Wi-Fi module is incompatible with the backed-up kernel')
            result['wifi_module_has_no_unresolved_symbols'] = True
            command('sleep 2; test -d /sys/class/net/wlan0; cat /proc/uptime')
            result['wifi_interface_created_in_emulator'] = True
        result['passed'] = True
        print(json.dumps(result), flush=True)
    except Exception as error:
        result['error'] = str(error)
        print(json.dumps(result), flush=True)
        raise
    finally:
        console.close()
        (directory / 'console.txt').write_bytes(transcript)
        suffix = '-wifi' if args.probe_wifi else ''
        (ROOT / f'build/recovery-{args.kernel}{suffix}-validation.json').write_text(json.dumps(result, indent=2) + '\n')
        if args.probe_wifi and result['passed']:
            (ROOT / f'build/recovery-{args.kernel}-validation.json').write_text(json.dumps(result, indent=2) + '\n')
        if args.image and result['passed']:
            name = 'device-recovery-rootfs.json' if args.kernel == 'diags' else 'device-main-rootfs.json'
            device_state = ROOT / 'build' / name
            if device_state.is_file():
                current = json.loads(device_state.read_text())
                if current['image'] == str(source_image) and current['sha256'] == result['source_image_sha256']:
                    current.update(emulator_boot_verified=True,
                                   emulator_validation=str(ROOT / f'build/recovery-{args.kernel}{suffix}-validation.json'))
                    device_state.write_text(json.dumps(current, indent=2) + '\n')
        try:
            control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            control.settimeout(5)
            control.connect(str(directory / 'control.sock'))
            stream = control.makefile('rwb', buffering=0)
            json.loads(stream.readline())
            stream.write(b'{"execute":"qmp_capabilities"}\n')
            while 'return' not in json.loads(stream.readline()):
                pass
            stream.write(b'{"execute":"quit"}\n')
            stream.close()
            control.close()
        except OSError:
            pass


if __name__ == '__main__':
    main()

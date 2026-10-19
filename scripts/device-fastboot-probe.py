"""Windows controller: one-time bootloader entry, read-only queries, return to stock.

Never issues download/flash/erase/setvar. It accepts only the already known USB
port and the Kindle fastboot VID/PID, and retains evidence in ignored build/.
"""
import json
import hashlib
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
USBIPD = r'C:\Program Files\usbipd-win\usbipd.exe'
BUS = '4-14'
WSL = ['wsl.exe', '-d', 'Ubuntu-24.04']
FASTBOOT = '/home/chris/kindle-build/fastboot-kindle/fastboot'


def run(command, timeout=15, check=True):
    return subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                          timeout=timeout, check=check)


def device():
    devices = json.loads(run([USBIPD, 'state']).stdout)['Devices']
    return next((item for item in devices if item['BusId'] == BUS), None)


def fastboot(*command):
    result = run(WSL + ['-u', 'root', '--', 'timeout', '10s', FASTBOOT, *command], timeout=15)
    return (result.stdout + result.stderr).strip()


def main():
    backup = json.loads((ROOT / 'build/full-backup-state.json').read_text(encoding='utf-8-sig'))
    current = device()
    if not backup['complete'] or current is None or not current['InstanceId'].startswith('USB\\VID_0525&PID_A4A2\\') or not current['ClientIPAddress']:
        raise ValueError('Verified backup and attached USB debug device on the known port are required')
    record = {'passed': False, 'bus': BUS, 'writes_block_devices': False, 'changes_idme': False,
              'self_restoring_shutdown_override': True,
              'queries': {}, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    state = ROOT / 'build/device-fastboot-validation.json'
    try:
        original = run(WSL + ['--', 'python3', '/mnt/d/kindle/scripts/device-ssh.py', '--command',
                              'cat /etc/upstart/shutdown.conf']).stdout.encode()
        (ROOT / 'build/stock-shutdown-before-fastboot.conf').write_bytes(original)
        record['original_shutdown_sha256'] = hashlib.sha256(original).hexdigest()
        reboot = run(WSL + ['--', 'python3', '/mnt/d/kindle/scripts/device-ssh.py', '--script',
                            '/mnt/d/kindle/device-probe/bin/test-fastboot-reboot.sh'])
        record['shutdown_request'] = (reboot.stdout + reboot.stderr).strip()
        deadline = time.monotonic() + 110
        saw_disconnected = False
        while time.monotonic() < deadline:
            current = device()
            if current is None:
                saw_disconnected = True
            elif current['InstanceId'].startswith('USB\\VID_1949&PID_D0D0\\'):
                record['fastboot_usb_seen'] = True
                record['usb_identity'] = '1949:d0d0'
                run([USBIPD, 'bind', '--busid', BUS])
                run([USBIPD, 'attach', '--wsl', 'Ubuntu-24.04', '--busid', BUS])
                record['queries']['version'] = fastboot('getvar', 'version')
                record['queries']['product'] = fastboot('getvar', 'product')
                record['queries']['max-download-size'] = fastboot('getvar', 'max-download-size')
                record['return_command'] = fastboot('reboot')
                record['passed'] = True
                break
            elif saw_disconnected and current['InstanceId'].startswith('USB\\VID_1949&PID_0004\\'):
                raise RuntimeError('Device returned to stock USB storage without an observed fastboot endpoint')
            time.sleep(0.5)
        else:
            raise TimeoutError('One-time fastboot USB endpoint was not detected within 110 seconds')
    except Exception as error:
        record['error'] = str(error)
        raise
    finally:
        state.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()

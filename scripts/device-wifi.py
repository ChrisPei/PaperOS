"""Restore stock Wi-Fi only after checking that both OTA executables are disabled."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
ssh = SourceFileLoader('paperos_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()


def remote(command):
    return subprocess.run(ssh.connection() + [command], capture_output=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--enable-stock', action='store_true')
    args = parser.parse_args()
    if args.enable_stock:
        remote('test ! -e /usr/bin/otaupd && test ! -e /usr/bin/otav3')
        remote('lipc-set-prop -i com.lab126.cmd wirelessEnable 1')
    proof = {'enabled': remote('lipc-get-prop com.lab126.cmd wirelessEnable').strip() == b'1',
             'ota_executables_disabled': True, 'connected': False}
    deadline = time.monotonic() + (35 if args.enable_stock else 0)
    while True:
        result = subprocess.run(ssh.connection() + ['wpa_cli -i wlan0 status'], capture_output=True)
        text = result.stdout.decode('utf-8', 'replace')
        (ROOT / 'build/private-wifi-status.txt').write_text(text)
        status = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        proof.update(wpa_state=status.get('wpa_state', 'unavailable'),
                     connected=status.get('wpa_state') == 'COMPLETED' and bool(status.get('ip_address')))
        if proof['connected'] or time.monotonic() >= deadline:
            break
        time.sleep(2)
    (ROOT / 'build/device-wifi-validation.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    main()

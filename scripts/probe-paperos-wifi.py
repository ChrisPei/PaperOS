"""Exercise the real WLAN driver, scan and airplane shutdown without credentials."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import time
import uuid
from importlib.machinery import SourceFileLoader

ROOT = Path('/mnt/d/kindle')
ssh = SourceFileLoader('wifi_probe_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()


def remote(command, data=None, check=True):
    result = subprocess.run(ssh.connection(22) + [command], input=data, capture_output=True, timeout=55)
    if check and result.returncode:
        raise RuntimeError((result.stderr + result.stdout).decode('utf-8', 'replace')[-2000:])
    return result


def main():
    token = uuid.uuid4().hex[:12]
    directory = ROOT / 'build' / ('wifi-hardware-' + token)
    directory.mkdir()
    ram = '/run/paperos-wifi-probe-' + token
    script = ROOT / 'os/rootfs-overlay/etc/init.d/S45paperos-wifi'
    subprocess.run(['/bin/sh', '-n', str(script)], check=True)
    if remote('pidof wpa_supplicant', check=False).returncode == 0:
        raise ValueError('An existing wireless session must be inspected before running the isolated radio test')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as output:
        output.add(script, arcname='wifi')
        config = b'ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=CN\n'
        entry = tarfile.TarInfo('wpa.conf')
        entry.size, entry.mode = len(config), 0o600
        output.addfile(entry, io.BytesIO(config))
    remote(f'umask 077; mkdir {ram} && tar xf - -C {ram}', archive.getvalue())
    checksum = hashlib.sha256(script.read_bytes()).hexdigest()
    remote(f"echo '{checksum}  {ram}/wifi' | sha256sum -c -")
    result = {'passed': False, 'script_sha256': checksum, 'credentials_used': False}
    try:
        start = remote(f'PAPEROS_WIFI_CONF={ram}/wpa.conf sh {ram}/wifi start', check=False)
        (directory / 'start.log').write_bytes(start.stdout + start.stderr)
        if start.returncode:
            raise RuntimeError('Wireless startup failed: ' + (start.stdout + start.stderr).decode('utf-8', 'replace')[-1500:])
        remote('ip link show wlan0 && /usr/sbin/wpa_cli -i wlan0 ping')
        remote('/usr/sbin/wpa_cli -i wlan0 scan')
        time.sleep(3)
        scan = remote('/usr/sbin/wpa_cli -i wlan0 scan_results').stdout
        (directory / 'private-scan.txt').write_bytes(scan)
        rows = [line for line in scan.splitlines() if len(line.split(b'\t')) == 5]
        if not rows:
            raise RuntimeError('The radio produced no scan results')
        result.update(interface='wlan0', wireless_driver_working=True, supplicant_working=True, networks_found=len(rows))
    finally:
        stop = remote(f'PAPEROS_WIFI_CONF={ram}/wpa.conf sh {ram}/wifi stop', check=False)
        (directory / 'stop.log').write_bytes(stop.stdout + stop.stderr)
        result['radio_driver_unloaded'] = remote('test ! -d /sys/module/dhd', check=False).returncode == 0
        result['passed'] = bool(result.get('networks_found')) and result['radio_driver_unloaded']
        (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (ROOT / 'build/wifi-hardware-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()

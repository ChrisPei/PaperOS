"""Verify the ARM SSH runtime's real key login and key-directory checks."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'build/usb-debug'


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run this isolated loopback test as WSL root')
    directory = Path(tempfile.mkdtemp(prefix='paperos-ssh-auth-', dir='/root'))
    auth = directory / 'auth'
    auth.mkdir(mode=0o700)
    shutil.copyfile(PAYLOAD / 'authorized_keys', auth / 'authorized_keys')
    (auth / 'authorized_keys').chmod(0o600)
    client = directory / 'client'
    shutil.copyfile(PAYLOAD / 'client_ed25519', client)
    client.chmod(0o600)
    known = directory / 'known_hosts'
    known.write_text((PAYLOAD / 'known_hosts').read_text().replace('[169.254.28.2]:2222', '[127.0.0.1]:32222'))
    log = (directory / 'server.log').open('wb')
    server = subprocess.Popen(['qemu-arm-static', str(PAYLOAD / 'libc.so'), '--library-path', str(PAYLOAD),
                               str(PAYLOAD / 'dropbear'), '-F', '-E', '-j', '-k', '-m', '-D', str(auth),
                               '-r', str(PAYLOAD / 'server_host_key'), '-p', '127.0.0.1:32222',
                               '-P', str(directory / 'server.pid')], stdout=log, stderr=subprocess.STDOUT)
    session = None
    try:
        time.sleep(0.5)
        if server.poll() is not None:
            raise RuntimeError('ARM server could not start')
        session = subprocess.Popen(['ssh', '-N', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                                    '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                                    '-o', 'ConnectTimeout=3', '-i', str(client), '-p', '32222', 'root@127.0.0.1'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if session.poll() is not None:
                raise RuntimeError(session.stderr.read().decode())
            if 'Pubkey auth succeeded' in (directory / 'server.log').read_text(errors='replace'):
                result = {'passed': True, 'public_key_authentication_verified': True,
                          'authorized_keys_inside_home': True, 'artifacts': str(directory),
                          'dropbear_sha256': hashlib.sha256((PAYLOAD / 'dropbear').read_bytes()).hexdigest(),
                          'libc_sha256': hashlib.sha256((PAYLOAD / 'libc.so').read_bytes()).hexdigest()}
                (PAYLOAD / 'auth-validation.json').write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps(result), flush=True)
                return
            time.sleep(0.1)
        raise RuntimeError('Server did not confirm key authentication')
    finally:
        if session is not None and session.poll() is None:
            session.terminate()
            session.wait(timeout=3)
        server.terminate()
        server.wait(timeout=3)
        log.close()


if __name__ == '__main__':
    main()

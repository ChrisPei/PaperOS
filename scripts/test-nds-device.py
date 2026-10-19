#!/usr/bin/env python3
"""Run original-ROM adapter checks on the pinned KT3 without taking its screen."""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import argparse
import io
import ipaddress
import json
import shlex
import subprocess
import tarfile
import uuid

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='192.0.2.20')
    args=parser.parse_args();ipaddress.ip_address(args.host)
    ssh=SourceFileLoader('nds_device_ssh',str(ROOT/'scripts/device-ssh.py')).load_module()
    connection=ssh.connection(22);connection[-1]='root@'+args.host
    connection[-1:-1]=['-o','HostKeyAlias=169.254.28.2']
    remote='/run/paperos-nds-test-'+uuid.uuid4().hex[:12]
    def call(command,data=None):
        result=subprocess.run(connection+[command],input=data,capture_output=True,timeout=65)
        if result.returncode:
            print(result.stdout.decode(errors='replace')[-5000:]);print(result.stderr.decode(errors='replace')[-5000:])
            raise RuntimeError(f'Device probe failed, exit={result.returncode}, evidence directory={remote}')
        return result.stdout
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w') as package:
        package.add(ROOT/'build/nds/player/nds-player-test',arcname='test')
        package.add(ROOT/'build/nds/paperos-idle.nds',arcname='probe.nds')
    q=shlex.quote(remote)
    call(f'mkdir -m 700 {q}; tar -xf - -C {q}; chmod 700 {q}/test',archive.getvalue())
    first=call(f'{q}/test {q}/probe.nds {q}/data')
    record=next(json.loads(line.split(' ',1)[1]) for line in first.decode().splitlines() if line.startswith('PAPEROS_NDS_PLAYER_TEST '))
    second=call(f'{q}/test {q}/probe.nds {q}/data {record["counter"]}')
    assert 'PAPEROS_NDS_REOPEN' in second.decode()
    record.update(execution_environment='physical Kindle KT3, headless',fresh_process_resume=True,
                  scope='Original two-screen homebrew probe; not Ace Attorney game validation',device_evidence_directory=remote)
    output=ROOT/'build/nds/player';output.mkdir(parents=True,exist_ok=True)
    (output/'device-test.log').write_bytes(first+second)
    (output/'validation-device.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()

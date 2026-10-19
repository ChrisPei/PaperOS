"""Run the bounded probe from the actual Kindle's Tailscale identity."""
import argparse
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--phase',choices=('before','after'),required=True)
args=parser.parse_args()
module=SourceFileLoader('home_access_ssh',str(root/'scripts/device-ssh.py')).load_module()
command=module.connection(22);command[-1]='root@192.0.2.20'
command[-1:-1]=['-o','HostKeyAlias=169.254.28.2']
def remote(script,data=None):
    result=subprocess.run(command+[script],input=data,capture_output=True,timeout=40)
    if result.returncode: raise RuntimeError('Device audit failed')
    return result.stdout
binary=(root/'build/probe-home-access').read_bytes()
remote('cat > /run/paperos/access-check',binary)
digest=hashlib.sha256(binary).hexdigest()
remote('sha256sum -c -',(digest+'  /run/paperos/access-check\n').encode())
try:
    result=json.loads(remote('chmod 700 /run/paperos/access-check && /run/paperos/access-check'))
finally:
    remote('rm -f /run/paperos/access-check')
result['verified_at']=datetime.now(timezone.utc).isoformat()
result['phase']=args.phase
(root/f'build/home-permissions-{args.phase}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if args.phase=='after':
    assert result['GatewayConfigured'] and not result['HARefreshCredentialPresent']
    assert result['Ports'][0]['Connected']
    assert all(not port['Connected'] for port in result['Ports'][1:])
    assert [r['Status'] for r in result['Requests']]==[200,403,403,403,403,405,405]
print(json.dumps(result,ensure_ascii=False),flush=True)

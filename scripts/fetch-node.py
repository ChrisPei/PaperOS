import hashlib,json,urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'downloads'
root.mkdir(exist_ok=True)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'}))
with opener.open('https://nodejs.org/dist/index.json',timeout=30) as response: releases=json.load(response)
release=next(r for r in releases if r['version'].startswith('v24.') and 'linux-x64' in r['files'])
version=release['version']; name=f'node-{version}-linux-x64.tar.xz'; base=f'https://nodejs.org/dist/{version}/'
with opener.open(base+'SHASUMS256.txt',timeout=30) as response: checksums=response.read().decode('ascii')
expected=next(line.split()[0] for line in checksums.splitlines() if line.split()[-1]==name)
target=root/name
if not target.exists():
    with opener.open(base+name,timeout=60) as response: contents=response.read(64*1024*1024+1)
    if len(contents)>64*1024*1024: raise ValueError('Unexpected Node archive size')
    target.write_bytes(contents)
actual=hashlib.sha256(target.read_bytes()).hexdigest()
if actual!=expected: raise ValueError('Node archive does not match the official SHA-256')
(root/'node-source.json').write_text(json.dumps({'version':version,'file':name,'source':base+name,'sha256':actual},indent=2)+'\n')
print(f'Node {version}: official SHA-256 matched',flush=True)

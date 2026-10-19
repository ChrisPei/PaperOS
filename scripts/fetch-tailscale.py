"""Fetch the pinned official ARM runtime used only for a remote home connection."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def main():
    lock = json.loads((ROOT / 'os/tailscale-runtime.json').read_text())
    archive = ROOT / 'downloads' / lock['url'].rsplit('/', 1)[-1]
    archive.parent.mkdir(exist_ok=True)
    published = urllib.request.urlopen(lock['checksum_url'], timeout=20).read(1024).decode().split()[0]
    if published != lock['sha256']:
        raise ValueError('Vendor checksum no longer matches the pinned archive')
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != lock['sha256']:
        temporary = archive.with_suffix('.downloading')
        with urllib.request.urlopen(lock['url'], timeout=90) as source, temporary.open('wb') as output:
            while block := source.read(1024 * 1024):
                output.write(block)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != lock['sha256']:
            raise ValueError('ARM runtime checksum mismatch')
        temporary.replace(archive)
    destination = ROOT / 'dist/tailscale-arm'
    destination.mkdir(exist_ok=True)
    records = []
    with tarfile.open(archive) as package:
        for name in ('tailscale', 'tailscaled'):
            members = [entry for entry in package.getmembers() if entry.isfile() and entry.name.rsplit('/', 1)[-1] == name]
            if len(members) != 1 or members[0].size > 150 * 1024 * 1024:
                raise ValueError('Unexpected runtime package contents')
            data = package.extractfile(members[0]).read()
            path = destination / name
            path.write_bytes(data);path.chmod(0o755)
            records.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    proof = {**lock, 'records': records}
    (ROOT / 'build/tailscale-runtime.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'version': lock['version'], 'verified': True, 'records': records}), flush=True)

if __name__ == '__main__':
    main()

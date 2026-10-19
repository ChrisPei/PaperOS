"""Put the optional vendor binaries in a separate, read-only file-backed image."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def command(*args):
    return subprocess.run(args, check=True, capture_output=True)

def main():
    proof = json.loads((ROOT / 'build/tailscale-runtime.json').read_text())
    for row in proof['records']:
        if hashlib.sha256((ROOT / 'dist/tailscale-arm' / row['name']).read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Runtime changed since vendor verification')
    image = ROOT / 'dist/paperos-tailnet.ext3'
    if image.exists():
        raise SystemExit('Image already exists; keep its previous validation or explicitly build a new filename')
    with image.open('xb') as output:
        output.truncate(96 * 1024 * 1024)
    command('mkfs.ext3', '-q', '-F', '-L', 'PAPEROSTAIL', '-O', '^64bit,^metadata_csum,^orphan_file', str(image))
    for row in proof['records']:
        source = ROOT / 'dist/tailscale-arm' / row['name']
        command('debugfs', '-w', '-R', 'write ' + str(source) + ' /' + row['name'], str(image))
        command('debugfs', '-w', '-R', 'set_inode_field /' + row['name'] + ' mode 0100755', str(image))
    license_file = ROOT / 'build/tailscale-LICENSE'
    license_file.write_bytes(urllib.request.urlopen('https://raw.githubusercontent.com/tailscale/tailscale/v' + proof['version'] + '/LICENSE', timeout=20).read(32768))
    command('debugfs', '-w', '-R', 'write ' + str(license_file) + ' /LICENSE', str(image))
    command('e2fsck', '-fn', str(image))
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    with image.open('rb') as source, gzip.open(str(image) + '.gz', 'wb', compresslevel=6) as output:
        while block := source.read(1024 * 1024):
            output.write(block)
    proof['image_sha256'] = digest
    proof['image_bytes'] = image.stat().st_size
    proof['image_gzip_bytes'] = Path(str(image) + '.gz').stat().st_size
    (ROOT / 'build/tailnet-image.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({k: proof[k] for k in ('version', 'image_sha256', 'image_bytes', 'image_gzip_bytes')}), flush=True)

if __name__ == '__main__':
    main()

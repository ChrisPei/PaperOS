"""Fetch an official, checksum-verified Go toolchain into the WSL build directory."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path('/mnt/d/kindle')
WORK = Path('/home/chris/kindle-build/toolchains')


def main():
    locked = json.loads((ROOT / "services/toolchain.json").read_text())
    releases = json.load(urllib.request.urlopen(locked["source"], timeout=30))
    if not any(item["version"] == locked["version"] for item in releases):
        releases = json.load(urllib.request.urlopen(locked["source"] + "&include=all", timeout=30))
    release = next(item for item in releases if item["version"] == locked["version"] and item["stable"])
    archive = next(item for item in release['files'] if item['os'] == 'linux' and item['arch'] == 'amd64' and item['kind'] == 'archive')
    if archive["sha256"] != locked["linux_amd64_sha256"]:
        raise ValueError("Official Go release differs from the reviewed toolchain lock")
    WORK.mkdir(parents=True, exist_ok=True)
    destination = WORK / release['version']
    saved = WORK / archive['filename']
    if not saved.exists():
        temporary = saved.with_suffix('.download')
        with urllib.request.urlopen('https://go.dev/dl/' + archive['filename'], timeout=60) as source, temporary.open('wb') as output:
            while block := source.read(1024 * 1024):
                output.write(block)
        temporary.rename(saved)
    if saved.stat().st_size != archive['size'] or hashlib.sha256(saved.read_bytes()).hexdigest() != archive['sha256']:
        raise ValueError('Official Go archive checksum or size mismatch')
    if not destination.exists():
        destination.mkdir()
        with tarfile.open(saved) as source:
            source.extractall(destination, filter='data')
    record = {'version': release['version'], 'archive_sha256': archive['sha256'], 'go': str(destination / 'go/bin/go'), 'source': 'https://go.dev/dl/?mode=json'}
    (ROOT / 'build/go-toolchain.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()

"""Copy a previously verified regular root image and provision the dashboard build."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path('/mnt/d/kindle')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    previous = json.loads((ROOT / 'build/device-main-rootfs.json').read_text())
    base = Path(previous['image'])
    if not base.is_file() or base.is_symlink() or digest(base) != previous['sha256']:
        raise ValueError('Previous private filesystem image does not match its verified record')
    destination = ROOT / 'build' / ('dashboard-rootfs-' + uuid.uuid4().hex[:12])
    destination.mkdir()
    image = destination / 'system.ext3'
    shutil.copyfile(base, image)
    sources = [
        (ROOT / 'dist/paperos-kt3', '/usr/bin/paperos', '0100755'),
        (ROOT / 'dist/paperos-services', '/usr/sbin/paperos-services', '0100755'),
        (ROOT / 'os/rootfs-overlay/etc/init.d/S60paperos-services', '/etc/init.d/S60paperos-services', '0100755'),
        (ROOT / 'os/rootfs-overlay/etc/init.d/S45paperos-wifi', '/etc/init.d/S45paperos-wifi', '0100755'),
        (ROOT / 'os/rootfs-overlay/usr/sbin/paperos-services-monitor', '/usr/sbin/paperos-services-monitor', '0100755'),
        (Path('/etc/ssl/certs/ca-certificates.crt'), '/etc/ssl/certs/ca-certificates.crt', '0100644'),
    ]
    for package in ('alarm', 'calendar', 'weather', 'mihome'):
        for filename, mode in (('manifest.conf', '0100644'), ('run.sh', '0100755')):
            sources.append((ROOT / 'examples' / (package + '.papp') / filename, '/var/lib/paperos/apps/org.paperos.' + package + '/' + filename, mode))
    seeds = sorted((ROOT / 'build/dashboard-preview').glob('data-*/weather-seed.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    if seeds:
        sources.append((seeds[0], '/var/lib/paperos/services/weather-seed.json', '0100644'))
    folders, actions, records = set(), [], []
    for source, target, mode in sources:
        for parent in reversed(Path(target).parents):
            if str(parent) != '/' and str(parent) not in folders:
                actions.append('mkdir ' + str(parent))
                folders.add(str(parent))
        actions.extend(('rm ' + target, f'write {source} {target}', f'set_inode_field {target} mode {mode}',
                        f'set_inode_field {target} uid 0', f'set_inode_field {target} gid 0'))
        records.append({'source': str(source), 'destination': target, 'sha256': digest(source)})
    actions.extend(('rm /var/lib/paperos/apps/org.paperos.clock/run.sh',
                    'rm /var/lib/paperos/apps/org.paperos.clock/manifest.conf',
                    'rmdir /var/lib/paperos/apps/org.paperos.clock'))
    instructions = destination / 'provision.debugfs'
    instructions.write_text('\n'.join(actions) + '\n')
    reply = subprocess.run(['debugfs', '-w', '-f', str(instructions), str(image)], capture_output=True, text=True, check=True)
    (destination / 'provision.log').write_text(reply.stdout + reply.stderr)
    for i, record in enumerate(records):
        target = destination / ('check-' + str(i))
        subprocess.run(['debugfs', '-R', f'dump {record["destination"]} {target}', str(image)], check=True, capture_output=True)
        if digest(target) != record['sha256']:
            raise ValueError('Provisioned file verification failed: ' + record['destination'])
        target.unlink()
    subprocess.run(['e2fsck', '-f', '-n', str(image)], check=True, capture_output=True)
    state = {'prepared': True, 'image': str(image), 'sha256': digest(image), 'base_sha256': previous['sha256'], 'records': records}
    (ROOT / 'build/dashboard-rootfs.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({'prepared': True, 'image': str(image), 'sha256': state['sha256']}), flush=True)


if __name__ == '__main__':
    main()

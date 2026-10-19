"""Undo Windows checkout CRLF conversion in task-owned Linux source mirrors."""
from pathlib import Path
import subprocess
import sys

root=Path(sys.argv[1]).resolve()
allowed=Path('/home/chris/kindle-build').resolve()
if root.parent!=allowed or root.name not in {'buildroot','qemu-eink'}:
    raise SystemExit('Refusing to normalize a path outside the known build source mirrors')
changed=0
source=Path('/mnt/d/kindle/tools') / root.name
if root.name=='qemu-eink': source=Path('/mnt/d/kindle/tools/qemu-eink')
links=0
index=subprocess.check_output(['git','-C',str(source),'ls-files','--stage','-z'])
for entry in index.split(b'\0'):
    if not entry or not entry.startswith(b'120000 '): continue
    relative=entry.split(b'\t',1)[1].decode('utf-8')
    path=root/relative
    if path.is_symlink(): continue
    if not path.is_file(): continue
    target=subprocess.check_output(['git','-C',str(source),'show',':'+relative]).decode('utf-8')
    # Upstream filesystem skeletons intentionally contain absolute links that
    # refer to the eventual guest root. Create the link only inside this mirror;
    # never follow it while normalizing or modify its destination.
    if not path.parent.resolve().is_relative_to(root):
        continue
    path.unlink()
    path.symlink_to(target)
    links+=1
for path in root.rglob('*'):
    if path.is_symlink() or not path.is_file() or '.git' in path.parts or 'build' in path.relative_to(root).parts:
        continue
    if path.stat().st_size>4*1024*1024:
        continue
    data=path.read_bytes()
    if b'\r\n' not in data or b'\0' in data:
        continue
    try: data.decode('utf-8')
    except UnicodeDecodeError: continue
    path.write_bytes(data.replace(b'\r\n',b'\n')); changed+=1
print(f'Restored {links} source symlinks; normalized LF in {changed} files')

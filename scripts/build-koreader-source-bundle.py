"""Publish the Kindle port's preferred sources, dependency caches, and GNU sources."""
from pathlib import Path
import argparse,gzip,hashlib,io,json,re,subprocess,tarfile

ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(1024*1024):h.update(b)
    return h.hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,default=Path.home()/'kindle-build/koreader-store-source')
    parser.add_argument('--gnu-source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    work=args.work.resolve();gnu=args.gnu_source.resolve();pin=json.loads((ROOT/'os/koreader-release.json').read_text());project=work/'koreader'
    lock=json.loads((work/'source-lock.json').read_text())
    if lock['modules'][0]['commit']!=pin['upstream_commit']:raise ValueError('Wrong KOReader source commit')
    ninja=project/'base/build/arm-linux-gnueabi/cmake/build.ninja'
    native=next(line for line in ninja.read_text().splitlines() if line.startswith('build download: phony '))
    required=set(re.findall(r'/thirdparty/([^/]+)/\1-download',native))
    if not required or 'inkview' in required:raise ValueError('Expected Kindle-specific sources')
    for name in required:
        if not (project/'base/build/arm-linux-gnueabi/thirdparty'/name/'stamp/download').exists():raise ValueError('Missing verified source download: '+name)
    gnu_receipt=json.loads((gnu/'sources.json').read_text())
    for source in gnu_receipt:
        for file in source['files']:
            if digest(gnu/file['name'])!=file['sha256']:raise ValueError('GNU source checksum changed')
    for path in (project/'base/thirdparty').glob('*/build/downloads/source/.git/config'):
        text=path.read_text()
        if re.search(r'(?i)(extraheader|password|oauth|token)',text) or re.search(r'https?://[^\s/]+@',text):raise ValueError('Credential-bearing Git metadata is not publishable')
    target=args.output.resolve();target.mkdir(parents=True,exist_ok=True);archive=target/('koreader-'+pin['port_version']+'-source.tar.gz')
    receipt={'port_version':pin['port_version'],'upstream':lock,'kindle_dependency_projects':sorted(required),
             'gnu_sources':gnu_receipt,'source_patch':'lua-spore-source-release.patch',
             'patch_note':'Use the maintainer release tarball from its LuaRocks source rock instead of the unreachable Git endpoint. Source version and publisher MD5 verified.'}
    def info(name,body):
        data=body.encode();entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o644;t.addfile(entry,io.BytesIO(data))
    def normalize(entry):
        entry.uid=entry.gid=entry.mtime=0;entry.uname=entry.gname=''
        return entry
    def upstream_filter(entry):
        rel=Path(entry.name).relative_to('KOReader');p=rel.parts
        if p[:2]==('base','build'):return None
        if len(p)>=4 and p[:2]==('base','thirdparty') and p[3]=='build':
            if p[2] not in required:return None
            if len(p)>4 and p[4]!='downloads':return None
        if '.git' in p:
            i=p.index('.git')
            if len(p)>i+1 and p[i+1] in ('logs','hooks'):return None
        if entry.name.endswith('.part'):return None
        if not(entry.isfile() or entry.isdir() or entry.issym() or entry.islnk()):raise ValueError('Unexpected source entry')
        return normalize(entry)
    own=['native','assets/stb_truetype.h','assets/Noto-LICENSE.txt','LICENSE','sources.lock.json','os/koreader-release.json',
         'examples/koreader.papp','scripts/build-koreader.py','scripts/build-koreader-overlay.sh','scripts/fetch-assets.py',
         'scripts/fetch-koreader-source.py','scripts/fetch-koreader-gnu-source.py','scripts/build-koreader-source-bundle.py']
    with archive.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0,compresslevel=3) as compressed,tarfile.open(fileobj=compressed,mode='w') as t:
        t.add(project,arcname='KOReader',filter=upstream_filter)
        for path in own:t.add(ROOT/path,arcname='PaperOS/'+path,filter=normalize)
        for repo in ['tools/FBInk','tools/FBInk/stb']:
            data=subprocess.check_output(['git','-C',str(ROOT/repo),'archive','--prefix=PaperOS/'+repo+'/','HEAD'])
            with tarfile.open(fileobj=io.BytesIO(data)) as src:
                for member in src:
                    if member.issym() or member.islnk():continue
                    normalize(member);t.addfile(member,src.extractfile(member) if member.isfile() else None)
        for file in sorted(gnu.iterdir()):
            if file.is_file() and not file.name.endswith('.part'):t.add(file,arcname='GNU-source/'+file.name,filter=normalize)
        t.add(work/'lua-spore-source-release.patch',arcname='lua-spore-source-release.patch',filter=normalize)
        info('SOURCE-RECEIPT.json',json.dumps(receipt,indent=2)+'\n')
        info('README-SOURCE.md','''# KOReader on PaperOS: corresponding source

KOReader/ is upstream v2026.07.1 with its pinned base, CRengine, translation
and font submodules, plus verified source downloads for the kindlepw2 target.
The source-lock receipt lists exact commits and source archive checksums.
Non-Kindle platform SDK downloads, test books and the Android launcher are omitted.
The only source-tree change is the documented Lua-Spore download-method patch:
the maintainer release archive replaces the same version's unreachable Git URL.
The LuaRocks publisher MD5 and upstream dependency verification both passed.
Cached Git dependencies retain their public origin/object metadata for rebuilding;
local Git logs and hooks are omitted. No device data or credentials are inputs.

To build upstream, install make, CMake 3.x, Ninja, Meson and an ARM soft-float
C/C++ compiler. Run `make -C KOReader TARGET=kindlepw2` using the upstream build
instructions. Dependency archives/caches are included so original servers are
not required for the initial source download. The original upstream build files,
patches and licenses are all retained. This is source, not an additional device image.

PaperOS/ contains all native overlay and adapter source plus FBInk/stb sources.
Set PAPEROS_MUSL_PREFIX to the ARM EABI soft-float musl cross-compiler prefix;
run `bash scripts/build-koreader-overlay.sh`, then `python3 scripts/build-koreader.py`
from PaperOS/. The official upstream ZIP is SHA-256 pinned by os/koreader-release.json.
GNU-source/ contains exact Ubuntu glibc, libgcc and cross-runtime packaging sources,
including DSC files, original source archives, patches and their checksums.
Use the Debian/Ubuntu source-package build rules when rebuilding those libraries.
The package pins installed cross-runtime binary versions before assembling its
read-only runtime image. Root font assets are fetched under their original license.

KOReader retains AGPL-3.0; PaperOS/FBInk retain GPL-3.0-or-later. GNU libraries,
fonts and dependencies keep their own included licenses and copyright notices.
This archive accompanies the KOReader PaperOS binary package at the same release.
''')
    print(json.dumps({'source_archive':str(archive),'bytes':archive.stat().st_size,'sha256':digest(archive),'kindle_projects':len(required)}),flush=True)
if __name__=='__main__':main()

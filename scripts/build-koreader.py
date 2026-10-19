"""Build the official KOReader release into a bounded PaperOS application package."""
from pathlib import Path
import gzip,hashlib,json,os,shutil,subprocess,zipfile,urllib.request

ROOT=Path(__file__).resolve().parents[1]
RELEASE=json.loads((ROOT/'os/koreader-release.json').read_text())
VERSION=RELEASE['upstream_version']
PORT_VERSION=RELEASE['port_version']
BUILD=Path(os.environ.get('PAPEROS_BUILD_HOME',str(Path.home()/'kindle-build')))/('koreader-'+VERSION)
RUNTIME=BUILD/'runtime'
PACKAGE=ROOT/'dist/koreader.papp'
RELEASE_SHA=RELEASE['upstream_archive_sha256']

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    fields=dict(line.split('=',1) for line in (ROOT/'examples/koreader.papp/manifest.conf').read_text().splitlines() if '=' in line)
    if fields['version']!=PORT_VERSION or fields['id']!='org.paperos.koreader':raise ValueError('Port manifest differs from release pin')
    installed=dict(line.split('\t',1) for line in subprocess.check_output(['dpkg-query','-W',*RELEASE['gnu_runtime_packages']],text=True).splitlines())
    if installed!=RELEASE['gnu_runtime_packages']:raise ValueError('GNU runtime differs from the release pin; update source pins and port version first')
    archive=ROOT/f'downloads/koreader-kindlepw2-v{VERSION}.zip'
    if not archive.exists():
        archive.parent.mkdir(parents=True,exist_ok=True)
        request=urllib.request.Request(f'https://github.com/koreader/koreader/releases/download/v{VERSION}/'+archive.name,headers={'User-Agent':'PaperOS-KOReader-builder'})
        with urllib.request.urlopen(request,timeout=120) as response,archive.open('wb') as out:shutil.copyfileobj(response,out)
    if sha(archive)!=RELEASE_SHA:raise ValueError('Release digest mismatch')
    RUNTIME.mkdir(parents=True,exist_ok=True)
    if not (RUNTIME/'koreader/reader.lua').exists():
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                path=Path(entry.filename)
                if path.is_absolute() or '..' in path.parts or (entry.external_attr>>16)&0o170000==0o120000:raise ValueError('Unexpected release archive path')
                if path.parts and path.parts[0]=='koreader':
                    source.extract(entry,RUNTIME)
                    if not entry.is_dir():(RUNTIME/path).chmod((entry.external_attr>>16)&0o777 or 0o644)
    (RUNTIME/'gnu').mkdir(exist_ok=True)
    for name in ['ld-linux.so.3','libc.so.6','libm.so.6','libdl.so.2','libpthread.so.0','librt.so.1','libgcc_s.so.1']:
        shutil.copy2(Path('/usr/arm-linux-gnueabi/lib')/name,RUNTIME/'gnu'/name)
    PACKAGE.mkdir(parents=True,exist_ok=True)
    image=BUILD/'runtime.ext3'
    libraries={p.name:sha(p) for p in (RUNTIME/'gnu').iterdir()}
    inputs={'release_sha256':RELEASE_SHA,'gnu_libraries':libraries}
    stamp=BUILD/'runtime-inputs.json'
    previous={}
    try:previous=json.loads((PACKAGE/'sources.json').read_text())
    except (ValueError,OSError,KeyError):pass
    receipt_matches=(image.exists() and previous.get('release_sha256')==RELEASE_SHA and previous.get('gnu_libraries')==libraries and previous.get('runtime_sha256')==sha(image))
    stamp_matches=False
    try:
        recorded=json.loads(stamp.read_text());stamp_matches=(recorded['inputs']==inputs and recorded['runtime_sha256']==sha(image))
    except (ValueError,OSError,KeyError):pass
    if not image.exists() or not (receipt_matches or stamp_matches):
        staged=image.with_suffix('.ext3.new')
        with staged.open('wb') as f:f.truncate(128*1024*1024)
        subprocess.run(['mkfs.ext3','-q','-F','-m','0','-O','^64bit,^metadata_csum,^orphan_file','-d',str(RUNTIME),str(staged)],check=True)
        staged.replace(image)
    digest=sha(image)
    stamp.write_text(json.dumps({'inputs':inputs,'runtime_sha256':digest},sort_keys=True)+'\n')
    with image.open('rb') as source,(PACKAGE/'runtime.ext3.gz').open('wb') as target:
        with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0,compresslevel=6) as out:shutil.copyfileobj(source,out)
    (PACKAGE/'runtime.sha256').write_text(digest+'\n')
    for source in (ROOT/'examples/koreader.papp').iterdir():
        if source.is_file():shutil.copy2(source,PACKAGE/source.name)
    shutil.copyfile(RUNTIME/'koreader/COPYING',PACKAGE/'KOReader-COPYING.txt')
    shutil.copyfile(ROOT/'LICENSE',PACKAGE/'PaperOS-COPYING.txt')
    for name in ['libc6-armel-cross','libgcc-s1-armel-cross']:
        shutil.copyfile(Path('/usr/share/doc')/name/'copyright',PACKAGE/(name+'-copyright.txt'))
    (PACKAGE/'sources.json').write_text(json.dumps(dict(upstream='https://github.com/koreader/koreader',version=VERSION,port_version=PORT_VERSION,upstream_commit=RELEASE['upstream_commit'],
        release_sha256=RELEASE_SHA,runtime_sha256=digest,
        source_release='https://github.com/ChrisPei/paperos-apps/releases/tag/'+RELEASE['release_tag'],
        gnu_packages=subprocess.check_output(['dpkg-query','-W','libc6-armel-cross','libgcc-s1-armel-cross'],text=True).splitlines(),
        gnu_libraries=libraries),indent=2)+'\n')
    (PACKAGE/'SOURCES.md').write_text('KOReader upstream v'+VERSION+'; PaperOS port '+PORT_VERSION+'.\n\n'
        'Corresponding source and build instructions: https://github.com/ChrisPei/paperos-apps/releases/tag/'+RELEASE['release_tag']+'\n'
        'Download koreader-'+PORT_VERSION+'-source.tar.gz at that same release. It includes the pinned KOReader and Kindle dependency sources, '
        'Ubuntu GNU runtime source packages, and the PaperOS adapter/overlay source.\n\n'
        'KOReader retains AGPL-3.0 (KOReader-COPYING.txt). PaperOS overlay uses GPL-3.0-or-later (PaperOS-COPYING.txt). '
        'GNU libraries retain their LGPL/GPL runtime-exception terms; see the included copyright files. '
        'Upstream fonts and other third-party notices remain inside the read-only runtime. No Amazon firmware is included.\n')
    (PACKAGE/'run.sh').chmod(0o755)
    if not (PACKAGE/'paperos-overlay').exists():raise ValueError('Build the native overlay before packaging')
    (PACKAGE/'paperos-overlay').chmod(0o755)
    entries=list(PACKAGE.rglob('*'))
    if len(entries)>256 or sum(p.stat().st_size for p in entries if p.is_file())>64*1024*1024:raise ValueError('Package exceeds PaperOS limits')
    print(json.dumps(dict(package=str(PACKAGE),version=PORT_VERSION,image_sha256=digest,bytes=(PACKAGE/'runtime.ext3.gz').stat().st_size)))
if __name__=='__main__':main()

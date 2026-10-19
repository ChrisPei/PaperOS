"""Build the official KOReader release into a bounded PaperOS application package."""
from pathlib import Path
import gzip,hashlib,json,shutil,subprocess,zipfile,urllib.request

ROOT=Path(__file__).resolve().parents[1]
BUILD=Path('/home/chris/kindle-build/koreader-2026.07.1')
RUNTIME=BUILD/'runtime'
PACKAGE=ROOT/'dist/koreader.papp'
VERSION='2026.07.1'
RELEASE_SHA='ea1f575c54492a2c679d128b7f3210fd7d6a87e5f5a1ff1f7a7fe2080ff68f86'

def main():
    archive=ROOT/f'downloads/koreader-kindlepw2-v{VERSION}.zip'
    if not archive.exists():
        archive.parent.mkdir(parents=True,exist_ok=True)
        request=urllib.request.Request(f'https://github.com/koreader/koreader/releases/download/v{VERSION}/'+archive.name,headers={'User-Agent':'PaperOS-KOReader-builder'})
        with urllib.request.urlopen(request,timeout=120) as response,archive.open('wb') as out:shutil.copyfileobj(response,out)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=RELEASE_SHA:raise ValueError('Release digest mismatch')
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
    if not image.exists():
        with image.open('wb') as f:f.truncate(128*1024*1024)
        subprocess.run(['mkfs.ext3','-q','-F','-m','0','-O','^64bit,^metadata_csum,^orphan_file','-d',str(RUNTIME),str(image)],check=True)
    digest=hashlib.sha256(image.read_bytes()).hexdigest()
    with image.open('rb') as source,(PACKAGE/'runtime.ext3.gz').open('wb') as target:
        with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0,compresslevel=6) as out:shutil.copyfileobj(source,out)
    (PACKAGE/'runtime.sha256').write_text(digest+'\n')
    (PACKAGE/'manifest.conf').write_text('id=org.paperos.koreader\nname=KOReader\nversion='+VERSION+'\nexec=run.sh\ndescription=电子书阅读器：EPUB、PDF、MOBI 等格式\n',encoding='utf-8')
    for source in (ROOT/'examples/koreader.papp').iterdir():
        if source.is_file():shutil.copy2(source,PACKAGE/source.name)
    for name in ['libc6-armel-cross','libgcc-s1-armel-cross']:
        shutil.copyfile(Path('/usr/share/doc')/name/'copyright',PACKAGE/(name+'-copyright.txt'))
    (PACKAGE/'sources.json').write_text(json.dumps(dict(upstream='https://github.com/koreader/koreader',version=VERSION,
        release_sha256=RELEASE_SHA,runtime_sha256=digest,
        gnu_packages=subprocess.check_output(['dpkg-query','-W','libc6-armel-cross','libgcc-s1-armel-cross'],text=True).splitlines(),
        gnu_libraries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (RUNTIME/'gnu').iterdir()}),indent=2))
    (PACKAGE/'run.sh').chmod(0o755)
    entries=list(PACKAGE.rglob('*'))
    if len(entries)>256 or sum(p.stat().st_size for p in entries if p.is_file())>64*1024*1024:raise ValueError('Package exceeds PaperOS limits')
    print(json.dumps(dict(package=str(PACKAGE),image_sha256=digest,bytes=(PACKAGE/'runtime.ext3.gz').stat().st_size)))
if __name__=='__main__':main()

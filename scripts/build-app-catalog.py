"""Package redistributable apps and sign the immutable-version store catalog.

Does not include credentials, ROMs, device backups, or the private system image.
The signing key must already exist outside the publication directory.
"""
from pathlib import Path
import argparse,base64,gzip,hashlib,io,json,shutil,subprocess,tarfile,zipfile,urllib.request

ROOT=Path(__file__).resolve().parents[1]
PLUGIN_COMMIT='53de65f04142f4b5bfdb0bf597cd03fb132d1732'

def archive_app(source, target):
    with target.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as zipped,tarfile.open(fileobj=zipped,mode='w') as archive:
        for p in sorted(source.rglob('*')):
            if p.is_symlink() or not(p.is_dir() or p.is_file()):raise ValueError('Special file in application')
            info=archive.gettarinfo(str(p),arcname=source.name+'/'+str(p.relative_to(source)))
            info.uid=info.gid=info.mtime=0;info.uname=info.gname=''
            executable=p.suffix=='.sh'
            if p.is_file():
                with p.open('rb') as probe:executable=executable or probe.read(4)==b'\x7fELF'
            info.mode=0o755 if p.is_dir() or executable else 0o644
            if p.is_file():
                with p.open('rb') as data:archive.addfile(info,data)
            else:archive.addfile(info)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--signing-key',type=Path)
    parser.add_argument('--packages-only',action='store_true');parser.add_argument('--koreader-url',default='')
    parser.add_argument('--release',default='store-2026-10-20');args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True);assets=out/'assets';assets.mkdir(exist_ok=True)
    if not args.packages_only and not args.signing_key:parser.error('--signing-key is required to sign a catalog')
    if args.signing_key and out in args.signing_key.resolve().parents:raise ValueError('Signing key must stay outside publication directory')
    # Small app packages also live in Git, avoiding the separate github.com
    # release redirect path on networks where that host is unreachable.
    base='https://api.github.com/repos/ChrisPei/paperos-apps/contents/packages/'
    entries=[]
    for name in ['alarm','calendar','weather','mihome','muyu','koreader']:
        source=ROOT/('dist' if name in ('muyu','koreader') else 'examples')/(name+'.papp')
        fields=dict(line.split('=',1) for line in (source/'manifest.conf').read_text().splitlines() if '=' in line)
        target=assets/(name+'-'+fields['version']+'.papp.tar.gz');archive_app(source,target)
        address=base+target.name
        if name=='koreader':
            address=args.koreader_url
            if not address and not args.packages_only:
                pin=json.loads((ROOT/'os/koreader-release.json').read_text())
                request=urllib.request.Request('https://api.github.com/repos/ChrisPei/paperos-apps/releases/tags/'+pin['release_tag'],headers={'User-Agent':'PaperOS-catalog-builder'})
                with urllib.request.urlopen(request,timeout=30) as response:release=json.load(response)
                address=next(a['url'] for a in release['assets'] if a['name']==target.name)
        entries.append(dict(id=fields['id'],name=fields['name'],version=fields['version'],description=fields.get('description',''),kind='papp',platforms=['paperos','armv7-softfloat'],url=address,size=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),homepage='https://github.com/ChrisPei/PaperOS'))
    plugin=ROOT/'downloads'/('appstore-'+PLUGIN_COMMIT[:7]+'.zip')
    if not plugin.exists():raise ValueError('Fetch the pinned App Store source ZIP first')
    with zipfile.ZipFile(plugin) as z:
        if not any(n.endswith('/_meta.lua') for n in z.namelist()) or not any(n.endswith('/main.lua') for n in z.namelist()):raise ValueError('Not a KOReader plugin archive')
    target=assets/('appstore-'+PLUGIN_COMMIT[:12]+'.koplugin.zip');shutil.copyfile(plugin,target)
    entries.append(dict(id='koplugin.appstore',name='KOReader 插件商店',version='git:'+PLUGIN_COMMIT[:12],description='在 KOReader 中浏览、下载和管理社区插件。需先安装 KOReader。',kind='koplugin',platforms=['koreader'],url=base+target.name,size=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),homepage='https://github.com/omer-faruq/appstore.koplugin'))
    if args.packages_only:
        print(json.dumps({'packages':len(entries),'output':str(out),'catalog_signed':False}));return
    catalog=out/'catalog.json';catalog.write_text(json.dumps({'schema':'paperos-store-v1','name':'PaperOS 官方应用','packages':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    signature=subprocess.check_output(['openssl','pkeyutl','-sign','-rawin','-inkey',str(args.signing_key),'-in',str(catalog)])
    (out/'catalog.json.sig').write_text(base64.b64encode(signature).decode()+'\n')
    public=subprocess.check_output(['openssl','pkey','-in',str(args.signing_key),'-pubout','-outform','DER'])[-32:]
    (out/'catalog.pub').write_text(base64.b64encode(public).decode()+'\n')
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(assets.iterdir()) if p.is_file()))
    print(json.dumps({'packages':len(entries),'files':len(list(assets.iterdir())),'output':str(out)}))
if __name__=='__main__':main()

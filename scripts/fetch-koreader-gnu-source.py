"""Fetch exact Ubuntu source packages for the isolated GNU runtime; verify DSC hashes."""
from pathlib import Path
import argparse,concurrent.futures,hashlib,json,re,urllib.request

ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()
def get(url,target,expected=None):
    if target.exists() and (not expected or sha(target)==expected):return
    part=target.with_suffix(target.suffix+'.part')
    request=urllib.request.Request(url,headers={'User-Agent':'PaperOS-corresponding-source'})
    with urllib.request.urlopen(request,timeout=90) as response,part.open('wb') as f:
        while data:=response.read(1024*1024):f.write(data)
    if expected and sha(part)!=expected:raise ValueError('Source hash mismatch: '+url)
    part.replace(target)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True);receipts=[];downloads=[]
    pin=json.loads((ROOT/'os/koreader-release.json').read_text())
    for source in pin['gnu_sources']:
        name,version,pool=source['name'],source['version'],source['pool']
        dsc=out/(name+'_'+version+'.dsc')
        bases=['https://archive.ubuntu.com/ubuntu/pool/'+pool+'/',
               'https://launchpad.net/ubuntu/+archive/primary/+sourcefiles/'+name+'/'+version+'/']
        if source.get('snapshot'):bases.insert(1,'https://snapshot.ubuntu.com/ubuntu/'+source['snapshot']+'/pool/'+pool+'/')
        for base in bases:
            try:get(base+dsc.name,dsc);break
            except Exception:
                if base==bases[-1]:raise
        text=dsc.read_text();block=text.split('Checksums-Sha256:',1)[1].split('\nFiles:',1)[0];members=[]
        for line in block.splitlines():
            match=re.fullmatch(r' ([0-9a-f]{64}) +(\d+) +(\S+)',line)
            if not match:continue
            digest,size,filename=match.groups()
            if '/' in filename or '\\' in filename or filename.startswith('.'):raise ValueError('Unsafe source filename')
            downloads.append((base+filename,out/filename,digest));members.append(dict(name=filename,sha256=digest,bytes=int(size)))
        if not members:raise ValueError('Missing SHA-256 source checksums')
        receipts.append(dict(package=name,version=version,dsc=base+dsc.name,files=members))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:list(executor.map(lambda x:get(*x),downloads))
    (out/'sources.json').write_text(json.dumps(receipts,indent=2)+'\n')
    print(json.dumps({'gnu_source_packages':len(receipts),'files':len(downloads),'bytes':sum(p.stat().st_size for p in out.iterdir() if p.is_file())}),flush=True)
if __name__=='__main__':main()

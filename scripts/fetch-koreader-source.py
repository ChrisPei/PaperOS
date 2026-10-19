"""Fetch the exact stable KOReader source tree and Kindle-relevant submodules.

Preferred-source snapshots and downloaded third-party archives are published
separately from the small on-device application. No device files are consulted.
"""
from pathlib import Path
import argparse,configparser,hashlib,io,json,os,shutil,tarfile,urllib.request

ROOT=Path(__file__).resolve().parents[1]
RELEASE=json.loads((ROOT/'os/koreader-release.json').read_text())
COMMIT=RELEASE['upstream_commit']
def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'PaperOS-corresponding-source'})
    with urllib.request.urlopen(request,timeout=90) as response:return response.read()
def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,default=Path.home()/'kindle-build/koreader-store-source');args=p.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=True);cache=work/'snapshots';cache.mkdir(exist_ok=True)
    project=work/'koreader';receipts=[]
    def materialize(repo,commit,target):
        archive=cache/(repo.replace('/','-')+'-'+commit+'.tar.gz')
        url=f'https://codeload.github.com/{repo}/tar.gz/{commit}'
        if not archive.exists():
            data=fetch(url);temporary=archive.with_suffix('.part');temporary.write_bytes(data);temporary.replace(archive)
        else:data=archive.read_bytes()
        marker=target/'.paperos-source-commit'
        if not marker.exists():
            staging=work/('extract-'+repo.replace('/','-')+'-'+commit[:12]);staging.mkdir(exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(data)) as t:t.extractall(staging,filter='data')
            roots=list(staging.iterdir());assert len(roots)==1
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(roots[0],target,dirs_exist_ok=True,symlinks=True)
            marker.write_text(commit+'\n')
        elif marker.read_text().strip()!=commit:raise ValueError('Source checkout differs from requested commit: '+str(target))
        receipts.append(dict(repo=repo,commit=commit,url=url,sha256=hashlib.sha256(data).hexdigest(),path=str(target.relative_to(project))))
        modules=target/'.gitmodules'
        if not modules.exists():return
        config=configparser.ConfigParser();config.read(modules)
        tree=json.loads(fetch(f'https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1'))
        if tree.get('truncated'):raise ValueError('Git tree unexpectedly truncated')
        links={e['path']:e['sha'] for e in tree['tree'] if e['mode']=='160000'}
        for section in config.sections():
            path=config[section]['path'];url=config[section]['url']
            # Test documents and the Android launcher are not part of Kindle binaries.
            if path=='test' or path.startswith('platform/android/'):continue
            if not url.startswith('https://github.com/') or '..' in Path(path).parts:raise ValueError('Unexpected submodule')
            child=url.removeprefix('https://github.com/').removesuffix('.git')
            materialize(child,links[path],target/path)
    materialize('koreader/koreader',COMMIT,project)
    (work/'source-lock.json').write_text(json.dumps({'upstream':'v'+RELEASE['upstream_version'],'modules':receipts,'omitted_non_runtime':['test','platform/android/luajit-launcher']},indent=2)+'\n')
    print(json.dumps({'source':str(project),'modules':len(receipts)}),flush=True)
if __name__=='__main__':main()

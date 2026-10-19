"""Prepare an audited source-only tree. Never stage the private workspace wholesale."""
from pathlib import Path
import argparse,hashlib,json,re,shutil

ROOT=Path(__file__).resolve().parents[1]
DIRECTORIES=('native','services','os','examples','bridge','home_gateway','scripts','tests')
DENY_NAMES={'__pycache__','.git','node_modules','local-config.json','local-token.txt','.env'}
PRIVATE_LITERALS={'192.0.2.10':'192.0.2.10','192.0.2.20':'192.0.2.20','192.0.2.30':'192.0.2.30'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve()
    if out==ROOT or ROOT not in out.parents or 'build' not in out.relative_to(ROOT).parts:raise ValueError('Use a new directory under build/')
    if out.exists():raise ValueError('Refusing to overwrite an existing publication tree')
    out.mkdir(parents=True);receipt=[]
    candidates=[]
    for directory in DIRECTORIES:
        candidates.extend(p for p in (ROOT/directory).rglob('*') if p.is_file())
    candidates.extend(ROOT/n for n in ('README.md','APP-SDK.md','STORE.md','PUBLISH.md','LICENSE','sources.lock.json','.gitignore','send-app.cmd'))
    candidates.extend(ROOT/'assets'/n for n in ('Noto-LICENSE.txt','solar-terms-sources.json','sources.json'))
    for src in sorted(candidates):
        rel=src.relative_to(ROOT)
        if any(p in DENY_NAMES for p in rel.parts) or src.suffix.lower() in {'.pyc','.pem','.key','.nds','.sav','.dsv','.ext3','.gz','.zip','.exe','.dll','.so','.bin','.o','.a'}:continue
        if src.is_symlink():raise ValueError('Source symlink: '+str(rel))
        data=src.read_bytes()
        try:content=data.decode('utf-8')
        except UnicodeDecodeError:raise ValueError('Unexpected binary source: '+str(rel))
        if re.search(r'-----BEGIN (?:OPENSSH |RSA |EC |ED25519 )?PRIVATE KEY-----',content):raise ValueError('Private key marker: '+str(rel))
        if re.search(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|tskey-[a-z]+-[A-Za-z0-9]{20,})',content):raise ValueError('Credential marker: '+str(rel))
        for private,example in PRIVATE_LITERALS.items():content=content.replace(private,example)
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,encoding='utf-8',newline='\n')
        if src.stat().st_mode&0o111 or src.suffix=='.sh' or rel.parts[0]=='os' and src.name.startswith(('S0','S1','S3','S4','S5','S6','paperos-')):target.chmod(0o755)
        receipt.append({'path':str(rel),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    ignore=out/'.gitignore'
    ignore.write_text(ignore.read_text()+'\n*.pem\n*.key\n*.nds\n*.sav\n*.dsv\n.env\n*credentials*.json\n*token*.txt\n')
    (out/'OPEN-SOURCE.md').write_text('''# Source distribution

PaperOS is a native Linux userspace and application platform for the Kindle KT3.
The existing vendor kernel and device-specific firmware are supplied by the owner;
this repository does not distribute Amazon firmware, backups, credentials or games.
Only KT3 has been validated. Other Kindle models require their own hardware port.

Original PaperOS code is GPL-3.0-or-later (LICENSE). Third-party code retains its
own license. FBInk is GPL-3.0-or-later at the commit in sources.lock.json.
stb_truetype uses its MIT/public-domain dual license. Noto CJK is SIL OFL 1.1.
The Go service uses klauspost/compress under BSD-3-Clause (go.mod/go.sum).
KOReader, its plugins, and optional game emulators retain their respective licenses.
No commercial game ROMs are included or required by the launcher/store.

## Build the launcher and service

Use Linux or Ubuntu WSL, a C11 compiler, Python 3 and make. Fetch pinned sources
with `python3 scripts/fetch-sources.py` and public font/header assets with
`python3 scripts/fetch-assets.py`. `make -C native` builds the host renderer.
`bash scripts/build-services.sh` fetches and verifies the Go version pinned by
services/toolchain.json, then builds host and ARM soft-float services.

The native ARM build needs an ARM EABI soft-float musl toolchain and FBInk:
set PAPEROS_MUSL_PREFIX to its absolute prefix, then use scripts/build-muyu.sh
or scripts/build-koreader-overlay.sh as the cross-compilation example.
The full independent root filesystem is a Buildroot external tree in os/.
Some deployment/recovery scripts retain workstation path defaults; read their
arguments and adapt local paths before using them. They are not a universal flasher.
Never apply a KT3 boot image to another model. Preserve a verified recovery backup.

## Test

Build the host C program; run `go test -race ./...` inside services, and
`python3 -m unittest discover -s tests`. The optional framebuffer render test
`python3 scripts/test-store-ui.py` needs Pillow and the fetched Noto font.
Real hardware remains necessary for e-ink, touch, sleep and power verification.

The store catalog and app releases live in the separate paperos-apps repository.
STORE.md documents compatibility and installation boundaries. Signing keys are
never source files. Public example NAS addresses use RFC 5737 documentation IPs;
substitute your own addresses and retain restrictive network permissions.
''',encoding='utf-8')
    manifest=ROOT/'build/public-source-audit.json';manifest.write_text(json.dumps({'files':len(receipt),'bytes':sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),'source_only':True,'files_audit':receipt},indent=2))
    print(json.dumps({'directory':str(out),'source_files':len(receipt),'audit':str(manifest)}))
if __name__=='__main__':main()

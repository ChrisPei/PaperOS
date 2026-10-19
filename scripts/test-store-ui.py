"""Render real native store states using isolated, deterministic IPC fixtures."""
from pathlib import Path
import os, subprocess, tempfile, json
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/store-ui'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='paperos-store-ui-') as temp:
        work=Path(temp);catalog=work/'catalog.tsv';state=work/'state.tsv';apps=work/'apps'
        subprocess.run([str(ROOT/'build/host/paperos'),'--app-root',str(apps),'--install',str(ROOT/'examples/alarm.papp')],check=True,capture_output=True)
        catalog.write_text('paperos-store-v1\t1\nsource\tpaperos\tPaperOS 官方应用\thttps://example.org/catalog.json\tpaperos\ttrue\t-\n'
            'source\tcommunity\tZenPM 社区商店\thttps://example.org/manifest.json\tzenpm\ttrue\t-\n'
            'source\tkpm\tKPM 官方源\thttps://example.org/manifest.v2.json\tkpm\ttrue\t-\n'
            'preset\tpaperos\tPaperOS 官方应用\thttps://example.org/catalog.json\tpaperos\ttrue\tEd25519 签名目录\n'
            'preset\tzenpm\tZenPM 社区商店\thttps://example.org/manifest.json\tzenpm\tfalse\tEd25519 签名目录\n'
            'preset\tkoreader-contrib\tKOReader 社区插件\thttps://example.org/contrib\tkoreader-contrib\tfalse\t固定 Git 提交版本的 KOReader 插件\n'
            'preset\tkpm\tKPM 官方源\thttps://example.org/kpm\tkpm\ttrue\t可浏览目录；原厂系统包需要移植\n'
            'app\tpaperos:org.paperos.muyu\torg.paperos.muyu\t木鱼\t0.1.0\t-\tpapp\tPaperOS 官方应用\t205000\t-\t轻触墨水屏，记录每一次敲击。\tfalse\thttps://example.org/muyu.zip\t'+ 'a'*64+'\n'
            'app\tcommunity:koplugin.appstore\tkoplugin.appstore\tKOReader App Store\t1.0\t0.9\tkoplugin\t社区应用\t500000\t-\t在阅读器内管理社区插件。\ttrue\thttps://example.org/plugin.zip\t'+'b'*64+'\n')
        def render(name,taps=(),phase='idle',busy=False,sort_mode='popular'):
            lines=[line for line in catalog.read_text().splitlines() if not line.startswith('sort\t')];lines.insert(1,'sort\t'+sort_mode);catalog.write_text('\n'.join(lines)+'\n')
            state.write_text('paperos-services-v1\nnet\ttrue\tfalse\ttrue\t192.0.2.2\tDemo\tfalse\t-\nstore\t'+str(busy).lower()+'\t'+phase+'\t45\t1\t'+str(catalog)+'\t目录已更新 · 2 款应用\tjob-test\tpaperos:org.paperos.muyu\t'+'a'*64+'\n')
            pgm=OUT/(name+'.pgm');command=[str(ROOT/'build/host/paperos'),'--font',str(ROOT/'assets/NotoSansCJKsc-Regular.otf'),'--screen','store','--app-root',str(apps),'--services-file',str(state),'--render',str(pgm)]
            for x,y in taps:command+=['--tap',str(x),str(y)]
            subprocess.run(command,check=True,capture_output=True)
            with Image.open(pgm) as image:
                assert image.size==(600,800)
                image.save(OUT/(name+'.png'))
        render('discover');render('paperos-apps',[(300,190)]);render('reader-plugins',[(490,190)])
        render('details',[(200,360)]);render('ready',[(200,360)],'ready');render('download',[(200,360)],'downloading',True)
        render('sources',[(80,630)]);render('community-sources',[(80,630),(150,620)])
        render('source-filter',[(150,130),(150,130)])
        with catalog.open('a') as output:
            for i in range(300):output.write(f'app\tkpm:legacy{i}\tlegacy{i}\tLegacy {i}\t1.0\t-\tauto\tKPM 官方源\t0\t需要原厂系统\tLegacy package\tfalse\thttps://example.org/legacy.zip\t-\n')
            output.write('app\tcommunity:koplugin.last\tkoplugin.last\tLast community entry\t2.0\t-\tkoplugin\tZenPM 社区商店\t0\t-\tAppears beyond the previous 256-entry limit\tfalse\thttps://example.org/last.zip\t-\n')
        render('large-community-catalog',[(150,130),(150,130)])
        render('unsupported-packages',[(150,130),(150,130),(150,130),(360,130)])
        lines=catalog.read_text().splitlines()
        lines=[line+'\t624\t2026-09-11\tutility\tZenPM 社区商店' if line.startswith('app\tcommunity:koplugin.appstore\t') else line for line in lines]
        lines.extend([
            'app\tcommunity:koplugin.alpha\tkoplugin.alpha\tAlpha reading helper\t2.0\t-\tkoplugin\tZenPM\t0\t-\tRead with an adjustable guide line\tfalse\thttps://example.org/alpha.zip\t-\t500\t2026-10-18\tutility\tZenPM',
            'app\tcommunity:koplugin.zulu\tkoplugin.zulu\tZulu bookshelf\t1.0\t-\tkoplugin\tZenPM\t0\t-\tBrowse your books on a custom shelf\tfalse\thttps://example.org/zulu.zip\t-\t500\t2025-01-01\ttheme\tZenPM',
            'app\tcommunity:koplugin.unknown\tkoplugin.unknown\tUnknown project statistics\t1.0\t-\tkoplugin\tZenPM\t0\t-\tThis source does not publish a star count\tfalse\thttps://example.org/unknown.zip\t-\t-1\t2026-10-19\tutility\t-'])
        catalog.write_text('\n'.join(lines)+'\n')
        render('popular-ranking',[(150,130),(150,130)])
        render('recent-ranking',[(150,130),(150,130)],sort_mode='recent')
        render('name-ranking',[(150,130),(150,130)],sort_mode='name')
        render('ranked-details',[(150,130),(150,130),(200,270)])
        print(json.dumps({'native_screens':15,'directory':str(OUT)}))
if __name__=='__main__':main()

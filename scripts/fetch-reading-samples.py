"""Fetch public-domain/author-distributed books for real reader validation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib,json,urllib.request,zipfile,io,xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'downloads/reading-samples'
SOURCES=[
    ('Nahan.epub','https://www.gutenberg.org/ebooks/27166.epub3.images','Project Gutenberg / Lu Xun, Nahan'),
    ('Nahan.txt','https://www.gutenberg.org/ebooks/27166.txt.utf-8','Project Gutenberg / Lu Xun, Nahan'),
    ('Nahan.azw3','https://www.gutenberg.org/ebooks/27166.kf8.images','Project Gutenberg / Lu Xun, Nahan'),
    ('Nahan.mobi','https://www.gutenberg.org/ebooks/27166.kindle.images','Project Gutenberg / Lu Xun, Nahan'),
    ('Nahan-html.zip','https://www.gutenberg.org/cache/epub/27166/pg27166-h.zip','Project Gutenberg / Lu Xun, Nahan'),
    ('Alice.epub','https://www.gutenberg.org/ebooks/11.epub3.images','Project Gutenberg / Lewis Carroll, Alice in Wonderland'),
    ('ThinkPython2.pdf','https://greenteapress.com/thinkpython2/thinkpython2.pdf','Allen B. Downey / CC BY-NC 3.0'),
]
def fetch(row):
    name,url,source=row;path=DEST/name
    if not path.exists():
        request=urllib.request.Request(url,headers={'User-Agent':'PaperOS-reading-test/1.0'})
        with urllib.request.urlopen(request,timeout=90) as response:
            body=response.read(20*1024*1024+1)
        if len(body)>20*1024*1024:raise ValueError('Unexpected sample size')
        path.write_bytes(body)
    data=path.read_bytes()
    if name.endswith(('.epub','.zip')):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:archive.testzip()
    elif name.endswith(('.mobi','.azw3')):
        if data[60:68]!=b'BOOKMOBI':raise ValueError('Not a Kindle book: '+name)
    elif name.endswith('.pdf') and not data.startswith(b'%PDF-'):raise ValueError('Not PDF')
    elif name.endswith('.txt'):
        if '孔乙己' not in data.decode('utf-8-sig'):raise ValueError('Chinese source text missing')
    return dict(file=name,url=url,source=source,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),derived=False,
                supported_in_koreader=name!='Nahan.azw3')
def main():
    DEST.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:records=list(pool.map(fetch,SOURCES))
    with zipfile.ZipFile(DEST/'Nahan-html.zip') as archive:
        for entry in archive.infolist():
            path=Path(entry.filename)
            if path.is_absolute() or '..' in path.parts:raise ValueError('Unexpected archive path')
        archive.extractall(DEST/'Nahan-HTML')
    # Extra formats are explicitly derived from the downloaded open books.
    ns='http://www.gribuser.ru/xml/fictionbook/2.0';ET.register_namespace('',ns)
    doc=ET.Element('{'+ns+'}FictionBook');description=ET.SubElement(doc,'{'+ns+'}description')
    title=ET.SubElement(description,'{'+ns+'}title-info')
    ET.SubElement(title,'{'+ns+'}genre').text='prose_classic'
    author=ET.SubElement(title,'{'+ns+'}author');ET.SubElement(author,'{'+ns+'}first-name').text='鲁迅'
    ET.SubElement(title,'{'+ns+'}book-title').text='呐喊';ET.SubElement(title,'{'+ns+'}lang').text='zh'
    body=ET.SubElement(doc,'{'+ns+'}body');section=ET.SubElement(body,'{'+ns+'}section')
    for line in (DEST/'Nahan.txt').read_text(encoding='utf-8-sig').splitlines():
        if line.strip():ET.SubElement(section,'{'+ns+'}p').text=line
    ET.ElementTree(doc).write(DEST/'Nahan.fb2',encoding='utf-8',xml_declaration=True)
    import fitz
    with fitz.open(DEST/'ThinkPython2.pdf') as source,zipfile.ZipFile(DEST/'ThinkPython2-sample.cbz','w',zipfile.ZIP_DEFLATED) as target:
        for i in range(min(8,len(source))):
            page=source[i]
            target.writestr(f'{i+1:03d}.png',page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),colorspace=fitz.csGRAY).tobytes('png'))
    empty=DEST/'Alice-illustrations.cbz'
    if empty.exists() and empty.stat().st_size==22:empty.unlink()
    for name,origin in [('Nahan.fb2','Nahan.txt'),('ThinkPython2-sample.cbz','ThinkPython2.pdf')]:
        data=(DEST/name).read_bytes();records.append(dict(file=name,derived=True,source_file=origin,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    (DEST/'sources.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    (DEST/'来源说明.txt').write_text('PaperOS 格式试读书架\n\n呐喊（鲁迅）：Project Gutenberg #27166\nhttps://www.gutenberg.org/ebooks/27166\n\nAlice（Lewis Carroll）：Project Gutenberg #11\nhttps://www.gutenberg.org/ebooks/11\n\nThink Python 2（Allen B. Downey）：作者提供 PDF，CC BY-NC 3.0\nhttps://greenteapress.com/thinkpython2/thinkpython2.pdf\n\nFB2 由下载的《呐喊》UTF-8 原文转换；CBZ 是 Think Python PDF 前八页的灰度格式试读版。\n其他格式为原站下载文件，不移除 DRM。\n',encoding='utf-8')
    print(json.dumps([dict(file=r['file'],bytes=r['bytes'],derived=r['derived']) for r in records],ensure_ascii=False,indent=2))
if __name__=='__main__':main()

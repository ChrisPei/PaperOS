"""Download the official KT3 recovery image to the computer, never to a device."""
import argparse,hashlib,json,urllib.request
from pathlib import Path

URL="https://s3.amazonaws.com/firmwaredownloads/update_kindle_8th_5.16.2.1.1.bin"
SIZE=260857971
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(); p.add_argument("--proxy",default=""); a=p.parse_args()
    handler=urllib.request.ProxyHandler({"https":a.proxy}) if a.proxy else urllib.request.ProxyHandler()
    opener=urllib.request.build_opener(handler)
    folder=ROOT/"downloads"; folder.mkdir(exist_ok=True)
    final=folder/"update_kindle_8th_5.16.2.1.1.bin"
    partial=final.with_suffix(".partial")
    if not final.exists():
        req=urllib.request.Request(URL,headers={"User-Agent":"PaperOS-KT3-development"})
        with opener.open(req,timeout=60) as response, partial.open("wb") as out:
            received=0; marker=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                received+=len(chunk)
                if received>SIZE: raise ValueError("Recovery response exceeds expected size")
                out.write(chunk)
                if received//(32*1024*1024)>marker:
                    marker=received//(32*1024*1024); print(f"KT3 recovery: {received}/{SIZE} bytes",flush=True)
        if received!=SIZE: raise ValueError("Incomplete recovery image")
        partial.replace(final)
    if final.stat().st_size!=SIZE: raise ValueError("Recovery image size mismatch")
    digest=hashlib.sha256()
    with final.open("rb") as f:
        if f.read(4)!=b"SP01": raise ValueError("Unexpected Kindle package header")
        f.seek(0)
        for block in iter(lambda:f.read(1024*1024),b""): digest.update(block)
    record={"source":URL,"file":final.name,"bytes":SIZE,"sha256":digest.hexdigest(),"note":"Observed digest, not an independent authenticity signature check. This is a public reference image, not a backup of the attached device."}
    (folder/"recovery-source.json").write_text(json.dumps(record,indent=2)+"\n")
    print(f"Official reference image saved: {final}",flush=True)

if __name__=="__main__": main()

"""Fetch openly licensed rendering assets; record the exact content digests."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "NotoSansCJKsc-Regular.otf": "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
    "Noto-LICENSE.txt": "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/LICENSE",
    "stb_truetype.h": "https://raw.githubusercontent.com/nothings/stb/master/stb_truetype.h",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default="")
    args = parser.parse_args()
    handler = urllib.request.ProxyHandler({"http": args.proxy, "https": args.proxy}) if args.proxy else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(handler)
    dest = ROOT / "assets"
    dest.mkdir(exist_ok=True)
    records = []
    for name, url in ASSETS.items():
        target = dest / name
        if not target.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "PaperOS-KT3-development"})
            with opener.open(req, timeout=60) as response:
                contents = response.read(32 * 1024 * 1024 + 1)
            if not contents or len(contents) > 32 * 1024 * 1024:
                raise ValueError(f"Unexpected size for {name}")
            if name.endswith(".otf") and contents[:4] != b"OTTO":
                raise ValueError("Font is not an OpenType CFF font")
            target.write_bytes(contents)
        contents = target.read_bytes()
        records.append({"name": name, "source": url, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()})
        print(f"{name}: {len(contents)} bytes", flush=True)
    (dest / "sources.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()

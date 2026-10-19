"""Download a verified release to the workspace for review, never to the device."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "downloads/winterbreak"
DEST.mkdir(parents=True, exist_ok=True)
proxy = os.environ.get("PAPEROS_HTTPS_PROXY")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy} if proxy else {}))
def fetch(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "PaperOS-KT3"})
    with opener.open(request, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Unexpectedly large release")
    return data
release = json.loads(fetch("https://api.github.com/repos/KindleModding/WinterBreak/releases/latest", 2*1024*1024))
asset = next(item for item in release["assets"] if item["name"] == "WinterBreak.tar.gz")
data = fetch(asset["browser_download_url"], 20*1024*1024)
sha = hashlib.sha256(data).hexdigest()
if asset.get("digest") and asset["digest"] != "sha256:" + sha:
    raise ValueError("GitHub release digest mismatch")
(DEST / "WinterBreak.tar.gz").write_bytes(data)
out = DEST / "payload"
out.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    for item in archive:
        target = (out / item.name).resolve()
        if not target.is_relative_to(out.resolve()):
            raise ValueError("Archive path escapes review directory")
        if item.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(item).read())
        elif not item.isdir():
            raise ValueError("Unexpected special archive member")
record = {"tag": release["tag_name"], "release_page": release["html_url"], "url": asset["browser_download_url"], "bytes": len(data), "sha256": sha, "github_digest": asset.get("digest"), "notes": release.get("body", "")}
(DEST / "release.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: record[k] for k in ("tag", "release_page", "bytes", "sha256", "github_digest")}))

"""Download and unpack LanguageBreak for review; never change the Kindle."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "downloads/languagebreak"
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
release = json.loads(fetch("https://api.github.com/repos/notmarek/LanguageBreak/releases/latest", 2*1024*1024))
asset = next((item for item in release["assets"] if item["name"] == "LanguageBreak-16.11.23.tar.gz"), None)
if asset is None:
    print(json.dumps({"tag": release["tag_name"], "assets": [{"name": a["name"], "url": a["browser_download_url"], "size": a["size"]} for a in release["assets"]]}))
    raise SystemExit("Inspect release asset names before choosing a bundle")
data = fetch(asset["browser_download_url"], 20*1024*1024)
sha = hashlib.sha256(data).hexdigest()
if asset.get("digest") and asset["digest"] != "sha256:" + sha:
    raise ValueError("GitHub release digest mismatch")
(DEST / "LanguageBreak.tar.gz").write_bytes(data)
out = DEST / "payload"
out.mkdir(exist_ok=True)
members = []
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    for item in archive:
        target = (out / item.name).resolve()
        if not target.is_relative_to(out.resolve()):
            raise ValueError("Archive path escapes review directory")
        if item.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            contents = archive.extractfile(item).read()
            target.write_bytes(contents)
            members.append({"path": item.name, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()})
        elif not item.isdir():
            raise ValueError("Unexpected special archive member")
record = {"tag": release["tag_name"], "release_page": release["html_url"], "url": asset["browser_download_url"], "bytes": len(data), "observed_sha256": sha, "github_digest": asset.get("digest"), "notes": release.get("body", ""), "files": members}
(DEST / "release.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: record[k] for k in ("tag", "release_page", "bytes", "observed_sha256", "github_digest")}))
print(f"Unpacked {len(members)} regular files for review")

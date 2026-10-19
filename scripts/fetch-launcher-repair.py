"""Fetch pinned upstream repair packages for offline inspection; never install them."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://storage.gra.cloud.ovh.net/v1/AUTH_2ac4bfee353948ec8ea7fd1710574097/mr-public/"
PACKAGES = {
    "JailBreak-1.16.N-FW-5.x-hotfix.zip": "Touch/",
    "KUAL-c6ac782-20250419.tar.xz": "KUAL/",
    "kual-mrinstaller-1.7.N-r19303.tar.xz": "KUAL/",
}
out = ROOT / "downloads" / "launcher-repair"
out.mkdir(parents=True, exist_ok=True)
proxy = os.environ.get("PAPEROS_HTTPS_PROXY")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy} if proxy else {}))
records = []
for name, folder in PACKAGES.items():
    url = BASE + folder + name
    path = out / name
    if not path.exists():
        with opener.open(url, timeout=60) as response:
            data = response.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("Unexpectedly large repair package")
        path.write_bytes(data)
    data = path.read_bytes()
    destination = out / name.split(".")[0]
    destination.mkdir(exist_ok=True)
    def save(relative, content):
        target = (destination / relative).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise ValueError("Archive path escapes repair directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    save(item.filename, archive.read(item))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
            for item in archive:
                if item.isfile():
                    save(item.name, archive.extractfile(item).read())
                elif not item.isdir():
                    raise ValueError("Unexpected special archive member")
    records.append({"name": name, "url": url, "size": len(data), "observed_sha256": hashlib.sha256(data).hexdigest()})
    print(f"Fetched and unpacked {name}: {len(data)} bytes")
(out / "sources.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

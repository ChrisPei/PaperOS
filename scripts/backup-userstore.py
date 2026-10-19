"""Make a private, verified backup of exported Kindle files; not an eMMC backup."""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("G:/")
def identity():
    label = ctypes.create_unicode_buffer(256)
    serial = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(str(SOURCE), label, 256, ctypes.byref(serial), None, None, None, 0)
    if not ok or label.value != "Kindle":
        raise ValueError("G: is not a mounted Kindle volume")
    return serial.value
volume = identity()
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
destination = ROOT / "backups" / ("userstore-" + stamp)
destination.mkdir(parents=True, exist_ok=False)
records = []
excluded = {"System Volume Information", "$RECYCLE.BIN"}
def failed(error):
    raise error
for directory, dirs, files in os.walk(SOURCE, followlinks=False, onerror=failed):
    if Path(directory) == SOURCE:
        dirs[:] = [d for d in dirs if d not in excluded]
    for name in files:
        source = Path(directory) / name
        relative = source.relative_to(SOURCE)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = source.stat()
        h = hashlib.sha256()
        with source.open("rb") as f, target.open("xb") as output:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk); output.write(chunk)
        after = source.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise ValueError("Source changed during backup; keep the partial backup for inspection")
        with target.open("rb") as verified:
            verified_digest = hashlib.file_digest(verified, "sha256").hexdigest()
        if verified_digest != h.hexdigest():
            raise ValueError("Backup verification failed")
        shutil.copystat(source, target)
        records.append({"path": relative.as_posix(), "bytes": before.st_size, "sha256": h.hexdigest()})
if identity() != volume:
    raise ValueError("Volume changed during backup")
report = {"scope": "exported-user-storage-only", "complete": True, "created_utc": stamp, "excluded_windows_metadata_directories": sorted(excluded), "files": records}
(destination / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"destination": str(destination), "files": len(records), "bytes": sum(item["bytes"] for item in records), "scope": report["scope"]}))

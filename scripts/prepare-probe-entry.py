"""Prepare a Mesquito app that runs only the local hardware probe as its payload."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
release = ROOT / "downloads/winterbreak"
source = release / "payload"
destination = ROOT / "build/probe-entry"
destination.mkdir(parents=True, exist_ok=True)
for folder in ("mesquito", ".active_content_sandbox"):
    shutil.copytree(source / folder, destination / folder, dirs_exist_ok=True)
app = destination / "apps/local.paperos.probe"
app.mkdir(parents=True, exist_ok=True)
original_app = source / "apps/tech.hackerdude.winterbreak"
manifest = json.loads((original_app / "manifest.json").read_text())
manifest.update({"id": "local.paperos.probe", "name": "PaperOS hardware probe", "description": "Read hardware facts into /mnt/us/paperos/device-probe.txt", "version": 1})
(app / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
for name in ("icon.png", "LICENSE"):
    shutil.copyfile(original_app / name, app / name)
(app / "index.html").write_text('''<!DOCTYPE html>
<!-- Based on WinterBreak by HackerDude; GPL-3.0-or-later. -->
<html><head><meta charset="utf-8"><title>PaperOS hardware probe</title></head>
<body><h1>PaperOS hardware probe</h1><p>Reading hardware information. Wait 10 seconds, then reconnect USB.</p>
<script>
var kindle = window.kindle || top.kindle;
setTimeout(function () {
    kindle.messaging.sendMessage("com.lab126.pillow", "customDialog", {
        name: "../../../../../../mnt/us/apps/local.paperos.probe/dialoger",
        clientParams: {show: true, jsEnabled: false}
    });
}, 2000);
</script></body></html>
''', encoding="utf-8")
(app / "dialoger.html").write_text('''<!-- Based on WinterBreak by HackerDude; GPL-3.0-or-later. -->
<html><head><meta charset="utf-8"><script>
nativeBridge.accessHasharrayProperty("com.lab126.transfer", "request_upload", {
    url: "http://127.0.0.1",
    source_command: "/bin/sh /mnt/us/extensions/PaperOSProbe/bin/probe.sh",
    unique_id: "paperos_probe_" + (new Date()).getTime(),
    netid: 1, priority: 50, notify_progress_interval: 20,
    notify_pub: "com.lab126.archive", notify_prop: "transferProgressNotification"
});
</script></head></html>
''', encoding="utf-8")
probe = destination / "extensions/PaperOSProbe/bin/probe.sh"
probe.parent.mkdir(parents=True, exist_ok=True)
probe.write_bytes((ROOT / "device-probe/bin/probe.sh").read_bytes().replace(b"\r\n", b"\n"))
record = {"upstream": json.loads((release / "release.json").read_text()), "purpose": "Local read-only hardware probe via the WinterBreak nativeBridge entry; no upstream jailbreak installer", "files": [{"path": p.relative_to(destination).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(destination.rglob("*")) if p.is_file()]}
(ROOT / "build/probe-entry-source.json").write_text(json.dumps(record, indent=2) + "\n")
print(f"Prepared {len(record['files'])} files; command payload is only the local hardware probe.")

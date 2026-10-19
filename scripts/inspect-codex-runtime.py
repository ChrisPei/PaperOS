"""Try a read-only thread/list on an existing Codex control socket; start no daemon."""
import json
import os
from pathlib import Path
import subprocess

root = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
executables = sorted(root.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
if not executables:
    print(json.dumps({"available": False, "reason": "Codex CLI not found"}))
    raise SystemExit(0)
messages = [
    {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "paperos-read-only", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}},
    {"method": "initialized", "params": {}},
    {"id": 2, "method": "thread/list", "params": {"limit": 20, "archived": False, "sortKey": "updated_at"}},
]
process = subprocess.Popen([str(executables[0]), "app-server", "proxy"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    stdout, stderr = process.communicate(("\n".join(json.dumps(m) for m in messages) + "\n").encode(), timeout=6)
except subprocess.TimeoutExpired:
    process.kill(); stdout, stderr = process.communicate()
for line in stdout.splitlines():
    try:
        response = json.loads(line)
    except (ValueError, UnicodeError):
        continue
    if response.get("id") == 2 and "result" in response:
        rows = response["result"].get("data", [])
        states = {}
        for row in rows:
            state = row.get("status", {}).get("type", "unknown")
            states[state] = states.get(state, 0) + 1
        print(json.dumps({"available": True, "threads": len(rows), "states": states}))
        break
else:
    # No raw notifications, task titles or local paths are printed.
    print(json.dumps({"available": False, "reason": "Existing shared app-server socket did not return thread/list", "exit_code": process.returncode}))

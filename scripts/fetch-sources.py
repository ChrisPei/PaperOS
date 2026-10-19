"""Materialize exact source commits from sources.lock.json; preserve existing checkouts."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
for item in json.loads((ROOT / "sources.lock.json").read_text()):
    target = ROOT / "tools" / item["name"]
    if not (target / ".git").exists():
        if target.exists():
            raise ValueError(f"Preserve existing non-Git directory: {target}")
        subprocess.run(["git", "init", str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "remote", "add", "origin", item["url"]], check=True)
        subprocess.run(["git", "-C", str(target), "fetch", "--depth", "1", "origin", item["commit"]], check=True)
        subprocess.run(["git", "-C", str(target), "checkout", "--detach", item["commit"]], check=True)
    actual = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
    if actual != item["commit"]:
        raise ValueError(f"Existing checkout does not match the lock file: {item['name']}")
    if item["name"] == "FBInk":
        subprocess.run(["git", "-C", str(target), "submodule", "update", "--init", "stb"], check=True)
    print(f"Verified {item['name']}: {actual[:12]}")

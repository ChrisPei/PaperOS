#!/bin/bash
set -euo pipefail
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
if ! python3 - "$PAPEROS_ROOT" <<'PY'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
try:
    lock = json.loads((root / "services/toolchain.json").read_text())
    built = json.loads((root / "build/go-toolchain.json").read_text())
    valid = (lock["version"] == built["version"] and
             lock["linux_amd64_sha256"] == built["archive_sha256"] and Path(built["go"]).is_file())
except (OSError, ValueError, KeyError):
    valid = False
raise SystemExit(0 if valid else 1)
PY
then
    python3 "$PAPEROS_ROOT/scripts/fetch-go.py"
fi
PAPEROS_GO=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["go"])' "$PAPEROS_ROOT/build/go-toolchain.json")
mkdir -p "$PAPEROS_ROOT/build/host" "$PAPEROS_ROOT/dist"
cd "$PAPEROS_ROOT/services"
export CGO_ENABLED=0 GOTOOLCHAIN=local
"$PAPEROS_GO" build -trimpath -ldflags='-s -w' -o "$PAPEROS_ROOT/build/host/paperos-services" .
GOOS=linux GOARCH=arm GOARM=7 "$PAPEROS_GO" build -trimpath -ldflags='-s -w' -o "$PAPEROS_ROOT/dist/paperos-services" .

#!/bin/bash
set -euo pipefail
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
PAPEROS_NODE=${PAPEROS_NODE_DIR:-/home/chris/kindle-build/tools/node-v24.21.0-linux-x64/bin}
export PATH="$PAPEROS_NODE:/usr/local/bin:/usr/bin:/bin"
export REA_OBJDUMP_COMMAND=/usr/bin/arm-linux-gnueabi-objdump
mkdir -p "$PAPEROS_ROOT/build/rea"
npx --yes rea-agents@6.5.0 inspect-with-objdump \
    "$PAPEROS_ROOT/dist/paperos-kt3" file_headers --format json \
    > "$PAPEROS_ROOT/build/rea/paperos-file-headers.json"
npx --yes rea-agents@6.5.0 inspect-with-objdump \
    "$PAPEROS_ROOT/dist/paperos-kt3" section_headers --format json \
    > "$PAPEROS_ROOT/build/rea/paperos-sections.json"
sha256sum "$PAPEROS_ROOT/dist/paperos-kt3" > "$PAPEROS_ROOT/build/rea/analyzed-SHA256SUMS"
echo "REA static evidence saved to build/rea."

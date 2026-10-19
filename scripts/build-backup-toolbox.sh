#!/bin/bash
set -euo pipefail
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
PAPEROS_WORK=${PAPEROS_BUILD_DIR:-/home/chris/kindle-build}
PAPEROS_SOURCE="$PAPEROS_WORK/backup-toolbox-source"
PAPEROS_BUILD="$PAPEROS_WORK/backup-toolbox-build"
PAPEROS_ARCHIVE="$PAPEROS_WORK/buildroot/dl/busybox/busybox-1.38.0.tar.bz2"
PAPEROS_CROSS="$PAPEROS_WORK/output-kt3/host/bin/arm-buildroot-linux-musleabi-"
if [ ! -x "${PAPEROS_CROSS}gcc" ] || [ ! -f "$PAPEROS_ARCHIVE" ]; then
    echo 'The pinned Buildroot source download and ARM musl toolchain are required.' >&2
    exit 1
fi
printf '%s  %s\n' 34f9ea6ff8636f2c9241153b9114eefa9e65674a45318ae1ef95bb5f31c53bb2 "$PAPEROS_ARCHIVE" | sha256sum -c -
mkdir -p "$PAPEROS_SOURCE" "$PAPEROS_BUILD" "$PAPEROS_ROOT/dist"
if [ ! -f "$PAPEROS_SOURCE/Makefile" ]; then
    tar -xjf "$PAPEROS_ARCHIVE" -C "$PAPEROS_SOURCE" --strip-components=1
fi
make -s -C "$PAPEROS_SOURCE" O="$PAPEROS_BUILD" allnoconfig \
    > "$PAPEROS_ROOT/build/backup-toolbox-config.log" 2>&1
python3 - "$PAPEROS_BUILD/.config" "$PAPEROS_ROOT/os/backup-toolbox.config" <<'PY'
from pathlib import Path
import re
import sys
base, additions = map(Path, sys.argv[1:])
extra = additions.read_text().splitlines()
keys = {line.split('=', 1)[0] for line in extra if line.startswith('CONFIG_')}
lines = []
for line in base.read_text().splitlines():
    match = re.match(r'(CONFIG_\w+)=|# (CONFIG_\w+) is not set', line)
    if not match or (match[1] or match[2]) not in keys:
        lines.append(line)
(base.parent / 'seed.config').write_text('\n'.join(lines + extra) + '\n')
PY
make -s -C "$PAPEROS_SOURCE" O="$PAPEROS_BUILD" \
    KBUILD_DEFCONFIG="$PAPEROS_BUILD/seed.config" defconfig \
    >> "$PAPEROS_ROOT/build/backup-toolbox-config.log" 2>&1
make -s -C "$PAPEROS_SOURCE" O="$PAPEROS_BUILD" \
    CROSS_COMPILE="$PAPEROS_CROSS" EXTRA_CFLAGS='-mcpu=cortex-a9 -mfloat-abi=soft' \
    -j"${PAPEROS_JOBS:-8}" > "$PAPEROS_ROOT/build/backup-toolbox-build.log" 2>&1 || {
        tail -n 50 "$PAPEROS_ROOT/build/backup-toolbox-build.log"
        exit 1
    }
cp "$PAPEROS_BUILD/busybox" "$PAPEROS_ROOT/dist/paperos-backup-tools"
file "$PAPEROS_ROOT/dist/paperos-backup-tools"
sha256sum "$PAPEROS_ROOT/dist/paperos-backup-tools"
